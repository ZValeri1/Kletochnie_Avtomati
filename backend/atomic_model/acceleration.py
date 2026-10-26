"""Optional CUDA connectivity checks; CPU remains the authoritative fallback.

Only deterministic candidate validation runs on the GPU. Probability arithmetic,
candidate ordering, random draws and state commits stay identical on both paths.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
from collections import OrderedDict
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# One independent block per proposed move. All occupied metal nodes are roots,
# exactly as in Topology.validate_occupancy (metal itself need not be connected).
# Integer atomics make propagation race-free; the fixed point is independent of
# thread scheduling. Positions, occupancy and source are never modified.
_CONNECTIVITY_KERNEL = r'''
extern "C" __global__ void candidate_connectivity(
    const int* neighbors, const unsigned char* metal, const int* occupancy,
    const int* positions, const int* destinations, int atom_count,
    int degree, int moving_atom, int source, int* visited, int* results)
{
    int candidate = blockIdx.x;
    int destination = destinations[candidate];
    int* seen = visited + ((size_t)candidate * atom_count);
    __shared__ int changed;
    for (int i = threadIdx.x; i < atom_count; i += blockDim.x) {
        int site = i == moving_atom ? destination : positions[i];
        seen[i] = metal[site] ? 1 : 0;
    }
    __syncthreads();
    for (int round = 0; round < atom_count; ++round) {
        if (threadIdx.x == 0) changed = 0;
        __syncthreads();
        for (int i = threadIdx.x; i < atom_count; i += blockDim.x) {
            if (atomicAdd(seen + i, 0)) continue;
            int site = i == moving_atom ? destination : positions[i];
            for (int d = 0; d < degree; ++d) {
                int neighbor = neighbors[(size_t)site * degree + d];
                if (neighbor < 0) break;
                int other = neighbor == source ? -1 :
                    (neighbor == destination ? moving_atom : occupancy[neighbor]);
                if (other >= 0 && atomicAdd(seen + other, 0)) {
                    atomicExch(seen + i, 1);
                    atomicExch(&changed, 1);
                    break;
                }
            }
        }
        __syncthreads();
        if (!changed) break;
    }
    if (threadIdx.x == 0) results[candidate] = 1;
    __syncthreads();
    for (int i = threadIdx.x; i < atom_count; i += blockDim.x) {
        if (!seen[i]) atomicExch(results + candidate, 0);
    }
}
'''


@dataclass
class _DeviceTopology:
    indices: dict[str, int]
    neighbors: object
    metal: object
    degree: int


class ComputeBackend:
    """Thread-safe lazy CUDA selection, including runtime failure recovery.

    Use GAMMA_COMPUTE_DEVICE=cpu to force the original validator. Both auto and
    cuda prefer CUDA but fall back safely if the optional dependency/device fails.
    """

    def __init__(self, preference: str | None = None) -> None:
        self.preference = (preference or os.environ.get("GAMMA_COMPUTE_DEVICE", "auto")).lower()
        if self.preference not in {"auto", "cpu", "cuda"}:
            raise ValueError("GAMMA_COMPUTE_DEVICE must be auto, cpu or cuda")
        self._lock = threading.RLock()
        self._slots = threading.BoundedSemaphore(4)
        self._initialized = False
        self._cp = None
        self._np = None
        self._kernel = None
        self._device = None
        self._device_name = None
        self._reason = None
        self._topologies = OrderedDict()
        self._cuda_batches = 0
        self._cuda_candidates = 0
        self._fallbacks = 0

    def _initialize(self) -> None:
        with self._lock:
            if self._initialized:
                return
            self._initialized = True
            if self.preference == "cpu":
                self._reason = "CPU выбран настройкой GAMMA_COMPUTE_DEVICE"
                return
            try:
                cp = importlib.import_module("cupy")
                np = importlib.import_module("numpy")
                if cp.cuda.runtime.getDeviceCount() < 1:
                    raise RuntimeError("CUDA device not found")
                device = int(os.environ.get("GAMMA_CUDA_DEVICE", "0"))
                with cp.cuda.Device(device):
                    kernel = cp.RawKernel(_CONNECTIVITY_KERNEL, "candidate_connectivity")
                    kernel.compile()
                    # Actual kernel launch, not just driver/device discovery.
                    neighbors = cp.asarray([[-1]], dtype=cp.int32)
                    metal = cp.asarray([1], dtype=cp.uint8)
                    zero = cp.asarray([0], dtype=cp.int32)
                    seen = cp.empty(1, dtype=cp.int32)
                    result = cp.empty(1, dtype=cp.int32)
                    kernel((1,), (128,), (neighbors, metal, zero, zero, zero,
                        np.int32(1), np.int32(1), np.int32(0), np.int32(0), seen, result))
                    if int(result.get()[0]) != 1:
                        raise RuntimeError("CUDA self-test failed")
                    name = cp.cuda.runtime.getDeviceProperties(device)["name"]
                self._cp, self._np, self._kernel = cp, np, kernel
                self._device = device
                self._device_name = name.decode() if isinstance(name, bytes) else str(name)
                logger.info("CUDA candidate validation enabled on %s", self._device_name)
            except Exception as error:
                self._reason = f"CUDA недоступна: {type(error).__name__}: {error}"
                logger.warning("%s; using CPU", self._reason)

    def status(self) -> dict:
        self._initialize()
        with self._lock:
            return {
                "schema_version": 1,
                "preference": self.preference,
                "backend": "cuda" if self._cp is not None else "cpu",
                "device_name": self._device_name,
                "reason": self._reason,
                "accelerated_operation": "candidate_connectivity",
                "cuda_batches": self._cuda_batches,
                "cuda_candidates": self._cuda_candidates,
                "fallbacks": self._fallbacks,
            }

    def _device_topology(self, topology, cp, np) -> _DeviceTopology:
        # Cached arrays are immutable. Publishing them only after synchronization
        # allows concurrent simulation streams to reuse them safely.
        with self._lock:
            if topology in self._topologies:
                self._topologies.move_to_end(topology)
                return self._topologies[topology]
            indices = {key: i for i, key in enumerate(topology.sites)}
            degree = max(map(len, topology.contact_graph.values()))
            if len(indices) * (degree * 4 + 1) > 256 * 1024 * 1024:
                raise MemoryError("Topology exceeds the CUDA cache budget")
            neighbors = np.full((len(indices), degree), -1, dtype=np.int32)
            metal = np.zeros(len(indices), dtype=np.uint8)
            for key, index in indices.items():
                adjacent = topology.contact_graph[key]
                neighbors[index, :len(adjacent)] = [indices[item] for item in adjacent]
                metal[index] = key in topology.metal_domain.lattice_keys
            entry = _DeviceTopology(indices, cp.asarray(neighbors), cp.asarray(metal), degree)
            cp.cuda.get_current_stream().synchronize()
            self._topologies[topology] = entry
            while len(self._topologies) > 2:
                self._topologies.popitem(last=False)
            return entry

    def _validate_cuda(self, topology, state, atom_id, destinations):
        cp, np = self._cp, self._np
        if cp is None:
            return None
        with cp.cuda.Device(self._device), cp.cuda.Stream(non_blocking=True) as stream:
            graph = self._device_topology(topology, cp, np)
            ids = list(state.atoms)
            moving_atom = ids.index(atom_id)
            positions = np.fromiter((graph.indices[state.atoms[i]] for i in ids),
                                    dtype=np.int32, count=len(ids))
            occupancy = np.full(len(graph.indices), -1, dtype=np.int32)
            occupancy[positions] = np.arange(len(ids), dtype=np.int32)
            targets = np.asarray([graph.indices[key] for key in destinations], dtype=np.int32)
            # Bounded scratch allocations even when many large simulations run.
            if len(ids) * len(targets) * 4 > 128 * 1024 * 1024:
                raise MemoryError("Candidate batch exceeds the CUDA scratch budget")
            seen = cp.empty((len(targets), len(ids)), dtype=cp.int32)
            result = cp.empty(len(targets), dtype=cp.int32)
            d_occupancy, d_positions, d_targets = map(cp.asarray, (occupancy, positions, targets))
            self._kernel((len(targets),), (128,), (
                graph.neighbors, graph.metal, d_occupancy, d_positions, d_targets,
                np.int32(len(ids)), np.int32(graph.degree), np.int32(moving_atom),
                np.int32(positions[moving_atom]), seen, result,
            ))
            answer = result.get(stream=stream).astype(bool).tolist()
            stream.synchronize()
            return answer

    def validate_candidates(self, topology, state, atom_id, destinations) -> list[bool] | None:
        if not destinations:
            return []
        self._initialize()
        if self._cp is None:
            return None
        # The normal public state validation handles malformed states; do not
        # silently let an invalid occupancy map acquire different GPU semantics.
        try:
            state.validate(topology)
        except Exception:
            return None
        try:
            with self._slots:
                result = self._validate_cuda(topology, state, atom_id, destinations)
            if result is not None:
                with self._lock:
                    self._cuda_batches += 1
                    self._cuda_candidates += len(destinations)
            return result
        except Exception as error:
            # No state mutation or RNG draw has happened. The caller recomputes
            # the entire batch on CPU before probability calculation/selection.
            with self._lock:
                self._reason = f"Ошибка CUDA: {type(error).__name__}: {error}"
                self._cp = None
                self._fallbacks += 1
                self._topologies.clear()
            logger.warning("%s; this and subsequent batches use CPU", self._reason)
            return None


_default_backend = None
_default_lock = threading.Lock()


def get_compute_backend() -> ComputeBackend:
    global _default_backend
    with _default_lock:
        if _default_backend is None:
            _default_backend = ComputeBackend()
        return _default_backend
