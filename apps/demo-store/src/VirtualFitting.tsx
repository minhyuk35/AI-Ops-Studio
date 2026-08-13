import type { ProductDetail } from "@ai-ops/shared-types";
import {
  FilesetResolver,
  PoseLandmarker,
  type NormalizedLandmark,
} from "@mediapipe/tasks-vision";
import { useEffect, useRef, useState } from "react";

// 가상 피팅 (웹캠 실시간 착장) — Phase 0(웹캠 + 포즈 추적) + Phase 1(어깨
// 랜드마크에 상품 이미지를 2D 오버레이). 세그멘테이션·앞뒤 레이어링·3D 메쉬는
// docs/codilab-project-hub.html "가상 피팅" 로드맵의 Phase 2~4로 남겨둔다.
//
// 모델·WASM은 설치된 @mediapipe/tasks-vision 와 같은 버전(0.10.14)의 CDN에서
// 로드한다. 완전 오프라인/자체호스팅이 필요하면 이 두 URL의 파일을 public/ 에
// 받아 두고 경로만 바꾸면 된다.
const MEDIAPIPE_VERSION = "0.10.14";
const WASM_BASE = `https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@${MEDIAPIPE_VERSION}/wasm`;
const MODEL_URL =
  "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task";

type Status = "loading" | "running" | "denied" | "nocam" | "error";

// 사용자 조작(의류 표시·골격 표시·크기)을 RAF 루프가 항상 최신값으로 읽도록
// state 와 별개로 ref 에도 담아둔다.
interface Controls {
  garment: boolean;
  skeleton: boolean;
  scale: number;
  offsetY: number;
}

const CONNECTED_PAIRS: Array<[number, number]> = [
  [11, 12], [11, 13], [13, 15], [12, 14], [14, 16],
  [11, 23], [12, 24], [23, 24], [23, 25], [24, 26], [25, 27], [26, 28],
];

export default function VirtualFitting({
  product,
  onClose,
}: {
  product: ProductDetail;
  onClose: () => void;
}) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const controls = useRef<Controls>({ garment: true, skeleton: false, scale: 1, offsetY: 0 });

  const [status, setStatus] = useState<Status>("loading");
  const [errorMsg, setErrorMsg] = useState("");
  const [ui, setUi] = useState<Controls>(controls.current);
  const [snapshotTainted, setSnapshotTainted] = useState(false);
  const [hasPose, setHasPose] = useState(false);

  // 컨트롤 갱신: state(리렌더용) + ref(루프용) 동시에.
  const setControl = <K extends keyof Controls>(key: K, value: Controls[K]) => {
    controls.current = { ...controls.current, [key]: value };
    setUi(controls.current);
  };

  useEffect(() => {
    let cancelled = false;
    let raf = 0;
    let stream: MediaStream | null = null;
    let landmarker: PoseLandmarker | null = null;
    let lastVideoTime = -1;
    let poseVisible = false;
    let lastPose: NormalizedLandmark[] | undefined;

    // 상품 이미지를 캔버스에 그릴 수 있게 미리 로드. CORS 허용 이미지면
    // 스냅샷(toDataURL)까지 가능, 아니면 오버레이는 되지만 스냅샷만 막힌다.
    const garmentImg = new Image();
    let garmentReady = false;
    garmentImg.crossOrigin = "anonymous";
    garmentImg.onload = () => {
      garmentReady = true;
    };
    garmentImg.onerror = () => {
      // CORS 로 막히면 crossOrigin 없이 재시도(오버레이는 되고 스냅샷만 비활성).
      const retry = new Image();
      retry.onload = () => {
        garmentReady = true;
        (garmentImg as unknown as { _fallback: HTMLImageElement })._fallback = retry;
        if (!cancelled) setSnapshotTainted(true);
      };
      retry.src = product.image;
      (garmentImg as unknown as { _fallback?: HTMLImageElement })._fallback = retry;
    };
    garmentImg.src = product.image;
    const activeGarment = () =>
      (garmentImg as unknown as { _fallback?: HTMLImageElement })._fallback ?? garmentImg;

    async function start() {
      if (!navigator.mediaDevices?.getUserMedia) {
        setStatus("nocam");
        return;
      }
      // 1) 포즈 모델 로드 (GPU 실패 시 CPU 폴백)
      try {
        const vision = await FilesetResolver.forVisionTasks(WASM_BASE);
        try {
          landmarker = await PoseLandmarker.createFromOptions(vision, {
            baseOptions: { modelAssetPath: MODEL_URL, delegate: "GPU" },
            runningMode: "VIDEO",
            numPoses: 1,
          });
        } catch {
          landmarker = await PoseLandmarker.createFromOptions(vision, {
            baseOptions: { modelAssetPath: MODEL_URL, delegate: "CPU" },
            runningMode: "VIDEO",
            numPoses: 1,
          });
        }
      } catch (err) {
        if (cancelled) return;
        setErrorMsg("포즈 인식 모델을 불러오지 못했습니다. 네트워크를 확인해주세요.");
        setStatus("error");
        return;
      }
      if (cancelled) return;

      // 2) 웹캠 열기
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: "user", width: { ideal: 960 }, height: { ideal: 720 } },
          audio: false,
        });
      } catch (err) {
        if (cancelled) return;
        const name = (err as DOMException)?.name;
        setStatus(name === "NotAllowedError" || name === "SecurityError" ? "denied" : "error");
        if (name !== "NotAllowedError") setErrorMsg("카메라를 열 수 없습니다.");
        return;
      }
      if (cancelled) {
        stream.getTracks().forEach((t) => t.stop());
        return;
      }

      const video = videoRef.current;
      if (!video) return;
      video.srcObject = stream;
      await video.play().catch(() => {});
      setStatus("running");
      loop();
    }

    function loop() {
      raf = requestAnimationFrame(loop);
      const video = videoRef.current;
      const canvas = canvasRef.current;
      if (!video || !canvas || !landmarker || video.readyState < 2) return;

      if (canvas.width !== video.videoWidth) {
        canvas.width = video.videoWidth;
        canvas.height = video.videoHeight;
      }
      const ctx = canvas.getContext("2d");
      if (!ctx) return;

      // 셀피처럼 좌우 반전해서 그린다. 랜드마크도 같은 반전 변환 아래에서
      // 그리므로 좌표를 따로 뒤집을 필요가 없다.
      ctx.save();
      ctx.translate(canvas.width, 0);
      ctx.scale(-1, 1);
      ctx.drawImage(video, 0, 0, canvas.width, canvas.height);

      let landmarks: NormalizedLandmark[] | undefined;
      if (video.currentTime !== lastVideoTime) {
        lastVideoTime = video.currentTime;
        const result = landmarker.detectForVideo(video, performance.now());
        landmarks = result.landmarks[0];
      }
      // 마지막으로 잡힌 포즈를 보관해 프레임 사이 깜빡임을 줄인다.
      if (landmarks) lastPose = landmarks;
      const pose = landmarks ?? lastPose;

      const visibleNow = Boolean(pose);
      if (visibleNow !== poseVisible) {
        poseVisible = visibleNow;
        setHasPose(visibleNow);
      }

      if (pose) {
        if (controls.current.garment && garmentReady) drawGarment(ctx, canvas, pose);
        if (controls.current.skeleton) drawSkeleton(ctx, canvas, pose);
      }
      ctx.restore();
    }

    function drawGarment(
      ctx: CanvasRenderingContext2D,
      canvas: HTMLCanvasElement,
      pose: NormalizedLandmark[],
    ) {
      const ls = pose[11]; // 왼쪽 어깨
      const rs = pose[12]; // 오른쪽 어깨
      const lh = pose[23]; // 왼쪽 골반
      const rh = pose[24]; // 오른쪽 골반
      if (!ls || !rs) return;
      const lx = ls.x * canvas.width;
      const ly = ls.y * canvas.height;
      const rx = rs.x * canvas.width;
      const ry = rs.y * canvas.height;

      const shoulderDist = Math.hypot(rx - lx, ry - ly);
      const angle = Math.atan2(ry - ly, rx - lx);
      const img = activeGarment();
      const aspect = img.naturalHeight / img.naturalWidth || 1.25;
      // 옷은 어깨너비보다 넓다. 사용자 슬라이더(scale)로 미세조정.
      const width = shoulderDist * 2.35 * controls.current.scale;
      const height = width * aspect;

      const cx = (lx + rx) / 2;
      const cy = (ly + ry) / 2;
      // 골반이 잡히면 상의 길이를 몸통 비율에 맞춘다(대략).
      const torso =
        lh && rh ? Math.hypot((lh.x + rh.x) / 2 - (ls.x + rs.x) / 2, (lh.y + rh.y) / 2 - (ls.y + rs.y) / 2) * canvas.height : height;

      ctx.save();
      ctx.translate(cx, cy);
      ctx.rotate(angle);
      ctx.globalAlpha = 0.92;
      // 목선이 어깨선보다 살짝 위에 오도록 위로 올리고, offsetY 로 미세조정.
      const top = -height * 0.16 + controls.current.offsetY;
      const drawH = Math.max(height, torso * 1.15);
      ctx.drawImage(img, -width / 2, top, width, drawH);
      ctx.restore();
    }

    function drawSkeleton(
      ctx: CanvasRenderingContext2D,
      canvas: HTMLCanvasElement,
      pose: NormalizedLandmark[],
    ) {
      ctx.save();
      ctx.strokeStyle = "rgba(139,155,255,.9)";
      ctx.lineWidth = 3;
      for (const [a, b] of CONNECTED_PAIRS) {
        const pa = pose[a];
        const pb = pose[b];
        if (!pa || !pb) continue;
        ctx.beginPath();
        ctx.moveTo(pa.x * canvas.width, pa.y * canvas.height);
        ctx.lineTo(pb.x * canvas.width, pb.y * canvas.height);
        ctx.stroke();
      }
      ctx.fillStyle = "#f472b6";
      for (const p of pose) {
        ctx.beginPath();
        ctx.arc(p.x * canvas.width, p.y * canvas.height, 4, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.restore();
    }

    start();

    return () => {
      cancelled = true;
      cancelAnimationFrame(raf);
      if (stream) stream.getTracks().forEach((t) => t.stop());
      if (videoRef.current) videoRef.current.srcObject = null;
      landmarker?.close();
    };
    // 상품이 바뀌면 전체 재설정. 컨트롤은 ref 로 읽으므로 의존성에 없다.
  }, [product.image]);

  const takeSnapshot = () => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    try {
      const url = canvas.toDataURL("image/png");
      const a = document.createElement("a");
      a.href = url;
      a.download = `코디랩-가상피팅-${product.name}.png`;
      a.click();
    } catch {
      setSnapshotTainted(true);
    }
  };

  return (
    <div className="vf-overlay" role="dialog" aria-label="가상 피팅" onClick={onClose}>
      <div className="vf-modal" onClick={(e) => e.stopPropagation()}>
        <header className="vf-head">
          <div>
            <strong>가상 피팅</strong>
            <span>{product.name}</span>
          </div>
          <button className="vf-close" aria-label="닫기" onClick={onClose}>✕</button>
        </header>

        <div className="vf-stage">
          {/* video 는 캔버스 소스로만 쓰고 화면에는 캔버스만 보여준다 */}
          <video ref={videoRef} playsInline muted className="vf-video-hidden" />
          <canvas ref={canvasRef} className="vf-canvas" />

          {status === "loading" && <div className="vf-state">카메라·모델 준비 중…</div>}
          {status === "denied" && (
            <div className="vf-state">
              카메라 권한이 거부되었습니다.<br />
              브라우저 주소창의 카메라 아이콘에서 권한을 허용한 뒤 다시 열어주세요.
            </div>
          )}
          {status === "nocam" && (
            <div className="vf-state">이 브라우저·기기에서는 웹캠을 쓸 수 없습니다.</div>
          )}
          {status === "error" && <div className="vf-state">{errorMsg || "오류가 발생했습니다."}</div>}
          {status === "running" && !hasPose && (
            <div className="vf-hint">카메라 앞에서 <b>상반신</b>이 보이도록 서 주세요.</div>
          )}
        </div>

        <div className="vf-controls">
          <label className="vf-toggle">
            <input
              type="checkbox"
              checked={ui.garment}
              onChange={(e) => setControl("garment", e.target.checked)}
            />
            의류 겹치기
          </label>
          <label className="vf-toggle">
            <input
              type="checkbox"
              checked={ui.skeleton}
              onChange={(e) => setControl("skeleton", e.target.checked)}
            />
            포즈 골격
          </label>
          <label className="vf-slider">
            크기
            <input
              type="range" min={0.7} max={1.6} step={0.02}
              value={ui.scale}
              onChange={(e) => setControl("scale", Number(e.target.value))}
            />
          </label>
          <label className="vf-slider">
            위치
            <input
              type="range" min={-80} max={80} step={2}
              value={ui.offsetY}
              onChange={(e) => setControl("offsetY", Number(e.target.value))}
            />
          </label>
          <button
            className="vf-shot"
            disabled={status !== "running"}
            onClick={takeSnapshot}
          >
            📸 사진 저장
          </button>
        </div>

        <p className="vf-note">
          영상은 <b>이 브라우저 안에서만</b> 처리되며 서버로 전송·저장되지 않습니다.
          {snapshotTainted && " (이 상품 이미지는 사진 저장이 제한될 수 있어요.)"}
          <br />
          데모 단계라 상품 사진을 그대로 겹칩니다 — 실제 서비스에서는 배경이 투명한
          착장용 이미지를 쓰면 훨씬 자연스러워집니다.
        </p>
      </div>
    </div>
  );
}
