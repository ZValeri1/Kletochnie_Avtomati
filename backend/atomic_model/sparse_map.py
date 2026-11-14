"""Copy-on-write sharded overlay over an immutable baseline mapping."""
from collections.abc import MutableMapping

_DELETED = None  # Atom IDs and site keys are never None.


class SparseMap(MutableMapping):
    SHARDS = 256

    def __init__(self, baseline):
        self.baseline = baseline
        self.shards = [{} for _ in range(self.SHARDS)]
        self.owned = set(range(self.SHARDS))
        self.length = len(baseline)
        self.version = 0
        self.keys_version = 0

    def fork(self):
        other = object.__new__(type(self))
        other.baseline = self.baseline
        other.shards = self.shards.copy()
        self.owned.clear()
        other.owned = set()
        other.length, other.version, other.keys_version = self.length, self.version, self.keys_version
        return other

    def __deepcopy__(self, memo):
        # Values are immutable integers/strings and every write owns its shard.
        other = self.fork()
        memo[id(self)] = other
        return other

    def __getitem__(self, key):
        shard = self.shards[hash(key) % self.SHARDS]
        if key in shard:
            value = shard[key]
            if value is _DELETED:
                raise KeyError(key)
            return value
        return self.baseline[key]

    def _write(self, key, value):
        index = hash(key) % self.SHARDS
        if index not in self.owned:
            self.shards[index] = self.shards[index].copy()
            self.owned.add(index)
        self.shards[index][key] = value
        self.version += 1

    def __setitem__(self, key, value):
        if key not in self:
            self.length += 1
            self.keys_version += 1
        self._write(key, value)

    def __delitem__(self, key):
        self[key]
        self._write(key, _DELETED)
        self.length -= 1
        self.keys_version += 1

    def __iter__(self):
        for key in self.baseline:
            if self.shards[hash(key) % self.SHARDS].get(key, True) is not _DELETED:
                yield key
        for shard in self.shards:
            for key, value in shard.items():
                if value is not _DELETED and key not in self.baseline:
                    yield key

    def __len__(self):
        return self.length

    def changed_keys(self):
        return (key for shard in self.shards for key in shard)

    def difference_keys(self, other):
        from backend.atomic_model.regular_grid import IdealAtoms, IdealOccupied
        equivalent = isinstance(other, SparseMap) and self.baseline is other.baseline
        if isinstance(other, SparseMap) and type(self.baseline) is type(other.baseline):
            left, right = self.baseline, other.baseline
            if isinstance(left, IdealOccupied):
                left, right = left.atoms, right.atoms
            if isinstance(left, IdealAtoms):
                equivalent = left.dimensions == right.dimensions and left.offset == right.offset
        if not equivalent:
            return self.keys() | other.keys()
        return {key for left, right in zip(self.shards, other.shards) if left is not right
                for key in left.keys() | right.keys()}

    def __getstate__(self):
        # Rehash on another process: Python string hash seeds differ on Windows.
        return self.baseline, dict((key, value) for shard in self.shards for key, value in shard.items()), self.length, self.version, self.keys_version

    def __setstate__(self, payload):
        baseline, changes, length, version, keys_version = payload
        self.__init__(baseline)
        for key, value in changes.items():
            self.shards[hash(key) % self.SHARDS][key] = value
        self.length, self.version, self.keys_version = length, version, keys_version


class RelocatedOccupancy:
    """Read-only hypothetical move used by connectivity checks, without a state copy."""
    def __init__(self, occupied, source, destination, atom_id):
        self.occupied, self.source, self.destination, self.atom_id = occupied, source, destination, atom_id

    def __contains__(self, key):
        return key == self.destination or (key != self.source and key in self.occupied)
