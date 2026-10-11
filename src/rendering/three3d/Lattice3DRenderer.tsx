import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";

import type { RenderFrame } from "../common/snapshotMapper";

interface SceneRefs {
  renderer: THREE.WebGLRenderer;
  scene: THREE.Scene;
  camera: THREE.PerspectiveCamera;
  controls: OrbitControls;
  geometry: THREE.SphereGeometry;
  materials: Map<number, THREE.MeshBasicMaterial>;
  meshes: THREE.Mesh[];
  animation: number;
  disposed: boolean;
}

function atomColor(atom: RenderFrame["atoms"][number]): number {
  return atom.metal_relation === "outside"
    ? 0xef4444
    : atom.metal_relation === "boundary"
      ? 0x15803d
      : atom.site_kind === "interstitial"
        ? 0xfb923c
        : 0x22c55e;
}

export function Lattice3DRenderer({
  frame,
  onError,
}: {
  frame: RenderFrame;
  onError: (error: Error) => void;
}) {
  const host = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<Error | null>(null);
  const refs = useRef<SceneRefs | null>(null);
  const targetDimensions = useRef<string>("");

  // Create the renderer, scene, camera and OrbitControls exactly ONCE on
  // mount. Previously the whole scene was rebuilt on every frame, so during
  // a continuous run each incoming snapshot replaced the canvas and reset
  // the camera — zoom/rotate gestures were impossible.
  useEffect(() => {
    const element = host.current;
    if (!element) return;
    try {
      const scene = new THREE.Scene();
      scene.background = new THREE.Color("#07111f");
      const camera = new THREE.PerspectiveCamera(55, 720 / 520, 0.1, 1000);
      camera.position.set(8, 8, 10);
      const renderer = new THREE.WebGLRenderer({ antialias: true });
      renderer.setSize(720, 520);
      element.replaceChildren(renderer.domElement);
      const controls = new OrbitControls(camera, renderer.domElement);
      const geometry = new THREE.SphereGeometry(0.12, 12, 12);
      const state: SceneRefs = {
        renderer,
        scene,
        camera,
        controls,
        geometry,
        materials: new Map(),
        meshes: [],
        animation: 0,
        disposed: false,
      };
      refs.current = state;
      const render = () => {
        if (state.disposed) return;
        state.controls.update();
        state.renderer.render(state.scene, state.camera);
        state.animation = requestAnimationFrame(render);
      };
      render();
      return () => {
        state.disposed = true;
        cancelAnimationFrame(state.animation);
        state.controls.dispose();
        state.geometry.dispose();
        for (const material of state.materials.values()) material.dispose();
        state.renderer.dispose();
        element.replaceChildren();
        refs.current = null;
      };
    } catch (caught) {
      const failure = caught instanceof Error ? caught : new Error(String(caught));
      setError(failure);
      onError(failure);
      return;
    }
  }, []);

  // Update atom meshes when a new frame arrives. The camera and controls are
  // never touched here (except re-centering when lattice dimensions change,
  // i.e. when another simulation is selected), so the user keeps full
  // zoom/rotate control while the simulation runs.
  useEffect(() => {
    const state = refs.current;
    if (!state) return;
    try {
      const dimensionsKey = frame.dimensions.join("x");
      if (dimensionsKey !== targetDimensions.current) {
        targetDimensions.current = dimensionsKey;
        state.controls.target.set(
          (frame.dimensions[0] - 1) / 2,
          (frame.dimensions[1] - 1) / 2,
          (frame.dimensions[2] - 1) / 2,
        );
        state.controls.update();
      }

      while (state.meshes.length < frame.atoms.length) {
        const mesh = new THREE.Mesh(state.geometry);
        state.scene.add(mesh);
        state.meshes.push(mesh);
      }

      frame.atoms.forEach((atom, index) => {
        const mesh = state.meshes[index];
        const color = atomColor(atom);
        let material = state.materials.get(color);
        if (!material) {
          material = new THREE.MeshBasicMaterial({ color });
          state.materials.set(color, material);
        }
        mesh.material = material;
        mesh.position.set(
          atom.coordinate[0],
          atom.coordinate[1],
          atom.coordinate[2],
        );
        mesh.visible = true;
      });

      for (let i = frame.atoms.length; i < state.meshes.length; i += 1) {
        state.meshes[i].visible = false;
      }
    } catch (caught) {
      const failure = caught instanceof Error ? caught : new Error(String(caught));
      setError(failure);
      onError(failure);
    }
  }, [frame, onError]);

  return (
    <div data-testid="renderer-3d" className="renderer-3d" ref={host}>
      {error && <div className="renderer-fallback">3D renderer unavailable</div>}
    </div>
  );
}
