import { useEffect, useRef } from "react";
import * as THREE from "three";

// Minimal wireframe hero visual: a slowly rotating icosahedron rendered as
// white line-art on the hero's black background. Kept deliberately simple
// (no textures/lights) so it stays true to the flat black & white look
// rather than reading as a product-3D-viewer feature.
export function ThreeHero() {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(
      45,
      container.clientWidth / Math.max(container.clientHeight, 1),
      0.1,
      100,
    );
    camera.position.z = 6.4;

    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(container.clientWidth, container.clientHeight);
    container.appendChild(renderer.domElement);

    const outer = new THREE.Mesh(
      new THREE.IcosahedronGeometry(2.3, 1),
      new THREE.MeshBasicMaterial({ color: 0xffffff, wireframe: true, transparent: true, opacity: 0.9 }),
    );
    const inner = new THREE.Mesh(
      new THREE.IcosahedronGeometry(1.1, 0),
      new THREE.MeshBasicMaterial({ color: 0xffffff, wireframe: true, transparent: true, opacity: 0.35 }),
    );
    scene.add(outer, inner);

    let frameId = 0;
    const animate = () => {
      outer.rotation.x += 0.0016;
      outer.rotation.y += 0.0024;
      inner.rotation.x -= 0.0022;
      inner.rotation.y -= 0.0012;
      renderer.render(scene, camera);
      frameId = requestAnimationFrame(animate);
    };
    animate();

    const handleResize = () => {
      const width = container.clientWidth;
      const height = Math.max(container.clientHeight, 1);
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
      renderer.setSize(width, height);
    };
    const resizeObserver = new ResizeObserver(handleResize);
    resizeObserver.observe(container);

    return () => {
      cancelAnimationFrame(frameId);
      resizeObserver.disconnect();
      outer.geometry.dispose();
      (outer.material as THREE.Material).dispose();
      inner.geometry.dispose();
      (inner.material as THREE.Material).dispose();
      renderer.dispose();
      container.removeChild(renderer.domElement);
    };
  }, []);

  return <div ref={containerRef} className="hero-canvas" aria-hidden="true" />;
}
