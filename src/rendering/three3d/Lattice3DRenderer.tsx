import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";

import type { RenderFrame } from "../common/snapshotMapper";

export function Lattice3DRenderer({
  frame,
  onError,
}: {
  frame: RenderFrame;
  onError: (error: Error) => void;
}) {
  const host = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    const element = host.current;
    if (!element) return;
    let renderer: THREE.WebGLRenderer | undefined;
    let animation = 0;
    const materials: THREE.Material[] = [];
    try {
      const scene = new THREE.Scene();
      scene.background = new THREE.Color("#07111f");
      const camera = new THREE.PerspectiveCamera(55, 720 / 520, 0.1, 1000);
      camera.position.set(8, 8, 10);
      renderer = new THREE.WebGLRenderer({ antialias: true });
      renderer.setSize(720, 520);
      element.replaceChildren(renderer.domElement);
      const controls = new OrbitControls(camera, renderer.domElement);
      controls.target.set(
        (frame.dimensions[0] - 1) / 2,
        (frame.dimensions[1] - 1) / 2,
        (frame.dimensions[2] - 1) / 2,
      );
      controls.update();
      const geometry = new THREE.SphereGeometry(0.12, 12, 12);
      for (const atom of frame.atoms) {
        const color = atom.metal_relation === "outside"
          ? 0xef4444
          : atom.metal_relation === "boundary"
            ? 0x15803d
            : atom.site_kind === "interstitial"
              ? 0xfb923c
              : 0x22c55e;
        const material = new THREE.MeshBasicMaterial({
          color,
        });
        materials.push(material);
        const mesh = new THREE.Mesh(geometry, material);
        mesh.position.set(atom.coordinate[0], atom.coordinate[1], atom.coordinate[2]);
        scene.add(mesh);
      }
      const render = () => {
        controls.update();
        renderer?.render(scene, camera);
        animation = requestAnimationFrame(render);
      };
      render();
      return () => {
        cancelAnimationFrame(animation);
        controls.dispose();
        geometry.dispose();
        for (const material of materials) material.dispose();
        renderer?.dispose();
        element.replaceChildren();
      };
    } catch (caught) {
      const failure = caught instanceof Error ? caught : new Error(String(caught));
      setError(failure);
      onError(failure);
      return;
    }
  }, [frame, onError]);

  return (
    <div data-testid="renderer-3d" className="renderer-3d" ref={host}>
      {error && <div className="renderer-fallback">3D renderer unavailable</div>}
    </div>
  );
}
