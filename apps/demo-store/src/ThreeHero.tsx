import { useEffect, useRef } from "react";
import * as THREE from "three";

// A fashion-appropriate hero visual: a densely-segmented plane whose
// vertices ripple like draped cloth, rendered as fine white wireframe so it
// reads as woven fabric in motion rather than a generic tech-demo shape.
export function ThreeHero() {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(
      50,
      container.clientWidth / Math.max(container.clientHeight, 1),
      0.1,
      100,
    );
    camera.position.set(0, 3.4, 7.2);
    camera.lookAt(0, -0.4, 0);

    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(container.clientWidth, container.clientHeight);
    container.appendChild(renderer.domElement);

    const width = 16;
    const depth = 9;
    const segmentsX = 64;
    const segmentsY = 36;
    const geometry = new THREE.PlaneGeometry(width, depth, segmentsX, segmentsY);
    geometry.rotateX(-Math.PI / 2.3);
    const basePositions = Float32Array.from(geometry.attributes.position.array);

    const material = new THREE.MeshBasicMaterial({
      color: 0xffffff,
      wireframe: true,
      transparent: true,
      opacity: 0.55,
    });
    const cloth = new THREE.Mesh(geometry, material);
    scene.add(cloth);

    let frameId = 0;
    let elapsed = 0;
    const position = geometry.attributes.position;
    const animate = () => {
      elapsed += 0.006;
      for (let i = 0; i < position.count; i++) {
        const x = basePositions[i * 3];
        const z = basePositions[i * 3 + 2];
        const wave =
          Math.sin(x * 0.55 + elapsed * 1.5) * 0.34 +
          Math.cos(z * 0.5 + elapsed * 1.1) * 0.24;
        position.setY(i, wave);
      }
      position.needsUpdate = true;
      renderer.render(scene, camera);
      frameId = requestAnimationFrame(animate);
    };
    animate();

    const handleResize = () => {
      const w = container.clientWidth;
      const h = Math.max(container.clientHeight, 1);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h);
    };
    const resizeObserver = new ResizeObserver(handleResize);
    resizeObserver.observe(container);

    return () => {
      cancelAnimationFrame(frameId);
      resizeObserver.disconnect();
      geometry.dispose();
      material.dispose();
      renderer.dispose();
      container.removeChild(renderer.domElement);
    };
  }, []);

  return <div ref={containerRef} className="hero-canvas" aria-hidden="true" />;
}
