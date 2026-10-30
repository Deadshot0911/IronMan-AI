"use client";
import { useState, useRef, useMemo, useEffect } from "react";
import type { ReactNode, CSSProperties } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Mic, MessageSquare, History, Cpu, Minimize2, Maximize2, SendHorizontal } from "lucide-react";
import { Canvas, useFrame } from "@react-three/fiber";
import { Line } from "@react-three/drei";
import * as THREE from "three";

const CYAN = "#22e5ff";
const ORANGE = "#ff9a3c";
const VIOLET = "#8b5cff";
const MONO = "ui-monospace, SFMono-Regular, Menlo, monospace";

// --- DYNAMIC LINES COMPONENT ---
function DynamicLines() {
  const lineRef = useRef<THREE.Group>(null);
  const [lines, setLines] = useState<
    { id: number; start: THREE.Vector3; end: THREE.Vector3; opacity: number }[]
  >([]);
  const timer = useRef(0);
  const idCounter = useRef(0);

  useFrame((_, delta) => {
    if (!lineRef.current) return;
    timer.current += delta;

    if (timer.current > 0.15) {
      timer.current = 0;
      setLines((prev) => {
        let next = [...prev];
        if (Math.random() > 0.4) {
          const start = new THREE.Vector3(
            (Math.random() - 0.5) * 3.5,
            (Math.random() - 0.5) * 3.5,
            (Math.random() - 0.5) * 3.5
          );
          const end = start.clone().add(
            new THREE.Vector3(
              (Math.random() - 0.5) * 1.5,
              (Math.random() - 0.5) * 1.5,
              (Math.random() - 0.5) * 1.5
            )
          );
          next.push({ id: idCounter.current++, start, end, opacity: 0 });
        }
        next = next.map((l) => ({ ...l, opacity: Math.min(1, l.opacity + 0.1) }));
        if (next.length > 20) next.shift();
        return next;
      });
    }

    lineRef.current.rotation.x += delta * 0.05;
    lineRef.current.rotation.y += delta * 0.08;
    lineRef.current.rotation.z = Math.sin(Date.now() * 0.0004) * 0.1;
  });

  return (
    <group ref={lineRef}>
      {lines.map((line) => (
        <Line
          key={line.id}
          points={[line.start, line.end]}
          color="#7df3ff"
          lineWidth={1}
          transparent
          opacity={line.opacity * 0.35}
        />
      ))}
    </group>
  );
}

// --- 3D HOLOGRAM COMPONENT ---
function Hologram({
  state,
  isMinimized,
  hoveredButton,
}: {
  state: string;
  isMinimized: boolean;
  hoveredButton: string | null;
}) {
  const groupRef = useRef<THREE.Group>(null);

  const [positions, colors] = useMemo(() => {
    const count = 8000;
    const pos = new Float32Array(count * 3);
    const cols = new Float32Array(count * 3);

    const colorCyan = new THREE.Color("#22e5ff");
    const colorWhite = new THREE.Color("#ffffff");
    const colorViolet = new THREE.Color(VIOLET);

    for (let i = 0; i < count; i++) {
      const r = 1.1 + Math.random() * 0.5;
      const theta = 2 * Math.PI * Math.random();
      const phi = Math.acos(2 * Math.random() - 1);
      const noise = Math.sin(theta * 15) * Math.cos(phi * 15) * 0.2;

      pos[i * 3] = (r + noise) * Math.sin(phi) * Math.cos(theta);
      pos[i * 3 + 1] = (r + noise) * Math.sin(phi) * Math.sin(theta);
      pos[i * 3 + 2] = (r + noise) * Math.cos(phi);

      const rand = Math.random();
      const c = rand < 0.55 ? colorCyan : rand < 0.82 ? colorWhite : colorViolet;
      cols[i * 3] = c.r;
      cols[i * 3 + 1] = c.g;
      cols[i * 3 + 2] = c.b;
    }
    return [pos, cols];
  }, []);

  const customMaterial = useMemo(() => {
    return new THREE.ShaderMaterial({
      uniforms: {
        uBulgeDir: { value: new THREE.Vector3(0, 1, 0) },
        uBulgeStrength: { value: 0 },
      },
      vertexShader: `
        uniform vec3 uBulgeDir;
        uniform float uBulgeStrength;
        varying vec3 vColor;

        void main() {
          vColor = color;
          vec3 pos = position;

          float dotProduct = dot(normalize(pos), normalize(uBulgeDir + vec3(0.00001)));
          float bulgeFactor = smoothstep(0.0, 1.0, dotProduct) * uBulgeStrength;
          pos += normalize(pos) * bulgeFactor * 0.8;

          vec4 mvPosition = modelViewMatrix * vec4(pos, 1.0);
          gl_PointSize = 16.0 * (1.0 / -mvPosition.z);
          gl_Position = projectionMatrix * mvPosition;
        }
      `,
      fragmentShader: `
        varying vec3 vColor;
        void main() {
          float dist = length(gl_PointCoord - vec2(0.5));
          if (dist > 0.5) discard;
          float alpha = smoothstep(0.5, 0.0, dist);
          gl_FragColor = vec4(vColor, alpha * 1.5);
        }
      `,
      transparent: true,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
      vertexColors: true,
    });
  }, []);

  useFrame((frame, delta) => {
    if (!groupRef.current) return;
    const t = frame.clock.elapsedTime;

    groupRef.current.rotation.x += delta * 0.08;
    groupRef.current.rotation.y += delta * 0.12;
    groupRef.current.rotation.z = Math.sin(t * 0.3) * 0.1;

    const u = customMaterial.uniforms;
    let strength = 0;

    if (hoveredButton) {
      const targetDir = new THREE.Vector3();
      if (hoveredButton === "text") targetDir.set(0, 1, 0);
      if (hoveredButton === "voice") targetDir.set(1, 0, 0);
      if (hoveredButton === "memory") targetDir.set(0, -1, 0);
      if (hoveredButton === "engine") targetDir.set(-1, 0, 0);
      const inverseRotation = new THREE.Quaternion().copy(groupRef.current.quaternion).invert();
      targetDir.applyQuaternion(inverseRotation);
      u.uBulgeDir.value.lerp(targetDir, 0.1);
      strength = 1.0;
    }
    u.uBulgeStrength.value = THREE.MathUtils.lerp(u.uBulgeStrength.value, strength, 0.1);

    let targetScale = 1;
    if (state === "speaking") targetScale = 1.1 + Math.sin(t * 10) * 0.05;
    else if (state === "listening") targetScale = 1.0 + Math.sin(t * 5) * 0.02;
    groupRef.current.scale.lerp(new THREE.Vector3(targetScale, targetScale, targetScale), 0.1);
  });

  return (
    <group>
      <group ref={groupRef}>
        <points>
          <bufferGeometry>
            <bufferAttribute attach="attributes-position" args={[positions, 3]} />
            <bufferAttribute attach="attributes-color" args={[colors, 3]} />
          </bufferGeometry>
          <primitive object={customMaterial} attach="material" />
        </points>
      </group>
      {!isMinimized && <DynamicLines />}
    </group>
  );
}

// --- ICON BUTTON (glass puck set into the slab) ---
function IconButton({
  icon,
  label,
  onClick,
  active,
  hovered,
  side,
  badge,
  badgeOn,
}: {
  icon: ReactNode;
  label: string;
  onClick?: () => void;
  active: boolean;
  hovered: boolean;
  side: "top" | "bottom" | "left" | "right";
  badge?: string;
  badgeOn?: boolean;
}) {
  const labelPos: CSSProperties =
    side === "top"
      ? { bottom: "100%", left: "50%", transform: "translateX(-50%)", marginBottom: 14 }
      : side === "bottom"
      ? { top: "100%", left: "50%", transform: "translateX(-50%)", marginTop: 16 }
      : side === "left"
      ? { right: "100%", top: "50%", transform: "translateY(-50%)", marginRight: 14 }
      : { left: "100%", top: "50%", transform: "translateY(-50%)", marginLeft: 14 };

  const inset = "inset 0 2px 5px rgba(255,255,255,0.18), inset 0 -8px 14px rgba(0,0,0,0.7)";
  const look: CSSProperties = active
    ? {
        background: "radial-gradient(circle at 30% 22%, rgba(190,250,255,0.5), rgba(34,229,255,0.16) 52%, rgba(0,18,28,0.75) 100%)",
        color: "#e9fdff",
        boxShadow: `${inset}, 0 0 0 1px ${CYAN}, 0 0 28px rgba(34,229,255,0.55), 0 10px 22px rgba(0,0,0,0.8)`,
      }
    : hovered
    ? {
        background: "radial-gradient(circle at 30% 22%, rgba(210,196,255,0.4), rgba(139,92,255,0.14) 52%, rgba(14,6,30,0.75) 100%)",
        color: "#e3dbff",
        boxShadow: `${inset}, 0 0 0 1px rgba(139,92,255,0.85), 0 0 24px rgba(139,92,255,0.5), 0 10px 22px rgba(0,0,0,0.8)`,
      }
    : {
        background: "radial-gradient(circle at 30% 22%, rgba(255,255,255,0.2), rgba(255,255,255,0.04) 42%, rgba(0,0,0,0.55) 100%)",
        color: "#bfefff",
        boxShadow: `${inset}, 0 0 0 1px rgba(255,255,255,0.1), 0 10px 22px rgba(0,0,0,0.8)`,
      };

  return (
    <div style={{ position: "relative" }}>
      {active && <span className="jv-ring" />}
      <button
        onClick={onClick}
        aria-label={label}
        style={{
          position: "relative",
          width: 64,
          height: 64,
          padding: 0,
          border: "none",
          borderRadius: "50%",
          display: "grid",
          placeItems: "center",
          cursor: "pointer",
          outline: "none",
          transition: "all 0.3s ease",
          transform: hovered ? "scale(1.1)" : "scale(1)",
          ...look,
        }}
      >
        <span style={{ position: "relative", display: "grid", placeItems: "center" }}>{icon}</span>
      </button>

      {badge && (
        <span
          style={{
            position: "absolute",
            left: "50%",
            bottom: -8,
            transform: "translateX(-50%)",
            padding: "1px 7px",
            fontFamily: MONO,
            fontSize: 8,
            letterSpacing: "0.15em",
            whiteSpace: "nowrap",
            borderRadius: 8,
            background: "#04070a",
            border: `1px solid ${badgeOn ? CYAN : "rgba(255,255,255,0.18)"}`,
            color: badgeOn ? CYAN : "#7d97a0",
            boxShadow: badgeOn ? "0 0 10px rgba(34,229,255,0.35)" : "none",
            pointerEvents: "none",
          }}
        >
          {badge}
        </span>
      )}

      <div
        style={{
          position: "absolute",
          ...labelPos,
          padding: "5px 12px",
          background: "rgba(0,0,0,0.92)",
          color: "#bfefff",
          fontSize: 10,
          letterSpacing: "0.18em",
          textTransform: "uppercase",
          fontFamily: MONO,
          whiteSpace: "nowrap",
          borderRadius: 6,
          border: "1px solid rgba(34,229,255,0.3)",
          boxShadow: "0 0 12px rgba(34,229,255,0.2)",
          opacity: hovered ? 1 : 0,
          transition: "opacity 0.25s",
          pointerEvents: "none",
        }}
      >
        {label}
      </div>
    </div>
  );
}

// --- MAIN UI COMPONENT ---
export default function JarvisUI() {
  const [isListening, setIsListening] = useState(true);
  const [isProcessing, setIsProcessing] = useState(false);
  const [isTextMode, setIsTextMode] = useState(false);
  const [isMinimized, setIsMinimized] = useState(false);
  const [isSilent, setIsSilent] = useState(false);
  const [memoryOn, setMemoryOn] = useState(false);
  const [engine, setEngine] = useState({ mode: "Auto", name: "Auto", model: "" });
  const [showEngine, setShowEngine] = useState(false);
  const [miniHover, setMiniHover] = useState(false);
  const [hoveredButton, setHoveredButton] = useState<string | null>(null);
  const [vp, setVp] = useState({ w: 1280, h: 800 });
  const [messages, setMessages] = useState<{ from: "jarvis" | "you"; text: string }[]>([
    { from: "jarvis", text: "Good evening, Sir. How may I assist you?" },
  ]);
  const [input, setInput] = useState("");
  const chatEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const update = () => setVp({ w: window.innerWidth, h: window.innerHeight });
    update();
    window.addEventListener("resize", update);
    return () => window.removeEventListener("resize", update);
  }, []);

  // state pushed from Python
  useEffect(() => {
    const h = (e: Event) => {
      const d = (e as CustomEvent).detail;
      const s = typeof d === "string" ? { state: d } : d;
      if (s.state === "listening") {
        setIsListening(true);
        setIsProcessing(false);
      } else if (s.state === "processing" || s.state === "speaking") {
        setIsListening(false);
        setIsProcessing(true);
      } else if (s.state === "standby") {
        setIsListening(false);
        setIsProcessing(false);
      }
      if (typeof s.mini === "boolean") {
        setIsMinimized(s.mini);
        if (s.mini) setHoveredButton(null);
      }
      if (typeof s.silent === "boolean") setIsSilent(s.silent);
      if (typeof s.memory === "boolean") setMemoryOn(s.memory);
      if (s.engine) setEngine(s.engine);
    };
    window.addEventListener("jarvisState", h);
    return () => window.removeEventListener("jarvisState", h);
  }, []);

  useEffect(() => {
    if (isMinimized) setShowEngine(false);
  }, [isMinimized]);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // ---- messages to Python ----
  const send = (t: string) => window.dispatchEvent(new CustomEvent("jarvisCommand", { detail: t }));
  const act = (o: object) => window.dispatchEvent(new CustomEvent("jarvisAction", { detail: o }));
  const linked = () => !!(window as any).__jarvisLinked;
  const wake = () => {
    send("jarvis wake up");
    if (!linked()) setIsMinimized(false);
  };
  const minimize = () => {
    send("jarvis minimise and listen");
    if (!linked()) {
      setIsMinimized(true);
      setHoveredButton(null);
    }
  };
  const toggleMemory = () => {
    const v = !memoryOn;
    setMemoryOn(v);
    act({ action: "set_memory", on: v });
  };
  const pickEngine = (m: string) => {
    act({ action: "set_engine", engine: m });
    setEngine((e) => ({ ...e, mode: m }));
    setShowEngine(false);
  };
  const sendMessage = () => {
    const text = input.trim();
    if (!text) return;
    setMessages((m) => [...m, { from: "you", text }]);
    setInput("");
    send(text);
  };

  const hologramState = isProcessing ? "speaking" : isListening ? "listening" : "standby";
  const accent = isProcessing ? ORANGE : CYAN;
  const statusLabel = isProcessing ? "PROCESSING" : isListening ? "LISTENING" : "STANDBY";
  const engineShown = engine.name && engine.name !== "—" ? engine.name : engine.mode;
  const modelShort = (engine.model || "").replace("openai/", "");

  // sizing
  const compact = vp.w < 320; // real window is the small orb window
  const S = compact ? vp.w - 30 : Math.max(320, Math.min(700, vp.w - 24, vp.h - 24));
  const MINI = 170;
  const miniScale = compact ? 1 : MINI / S;
  const prevCompact = useRef(compact);
  const snap = prevCompact.current !== compact;
  useEffect(() => {
    prevCompact.current = compact;
  });
  const radius = S * 0.37;
  const ease = [0.65, 0, 0.35, 1] as const;
  const dur = snap ? 0 : 0.8;

  const buttons = [
    {
      id: "text",
      icon: <MessageSquare size={24} />,
      label: "Text Mode",
      onClick: () => setIsTextMode((v) => !v),
      active: isTextMode,
      angle: -90,
      side: "top" as const,
    },
    {
      id: "voice",
      icon: <Mic size={24} />,
      label: "Voice Mode",
      onClick: () => setIsTextMode(false),
      active: !isTextMode,
      angle: 0,
      side: "right" as const,
    },
    {
      id: "memory",
      icon: <History size={24} />,
      label: `Memory ${memoryOn ? "On" : "Off"}`,
      onClick: toggleMemory,
      active: memoryOn,
      angle: 90,
      side: "bottom" as const,
      badge: memoryOn ? "ON" : "OFF",
      badgeOn: memoryOn,
    },
    {
      id: "engine",
      icon: <Cpu size={24} />,
      label: "AI Engine",
      onClick: () => setShowEngine((v) => !v),
      active: showEngine,
      angle: 180,
      side: "left" as const,
      badge: engineShown.toUpperCase(),
      badgeOn: true,
    },
  ];

  const glassBtn: CSSProperties = {
    position: "fixed",
    top: 30,
    right: 30,
    zIndex: 100,
    width: 48,
    height: 48,
    borderRadius: "50%",
    display: "grid",
    placeItems: "center",
    cursor: "pointer",
    color: "#bfefff",
    border: "none",
    background: "radial-gradient(circle at 30% 22%, rgba(255,255,255,0.2), rgba(255,255,255,0.04) 45%, rgba(0,0,0,0.55) 100%)",
    boxShadow: "inset 0 2px 5px rgba(255,255,255,0.18), inset 0 -6px 12px rgba(0,0,0,0.7), 0 0 0 1px rgba(255,255,255,0.12), 0 8px 18px rgba(0,0,0,0.8)",
    padding: 0,
  };

  const slabW = isMinimized ? 200 : Math.max(0, vp.w - 24);
  const slabH = isMinimized ? 200 : Math.max(0, vp.h - 24);

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        background: "#000",
        overflow: "hidden",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      <style>{`
        html, body { background: #000 !important; margin: 0; }
        @keyframes jv-eq { 0%,100% { transform: scaleY(0.25); } 50% { transform: scaleY(1); } }
        @keyframes jv-pulse { 0% { transform: scale(1); opacity: .7; } 100% { transform: scale(1.55); opacity: 0; } }
        @keyframes jv-blink { 0%,100% { opacity: 1; } 50% { opacity: .35; } }
        @keyframes jv-sheen { 0% { transform: translateX(-140%) skewX(-20deg); } 100% { transform: translateX(340%) skewX(-20deg); } }
        .jv-ring { position:absolute; inset:0; border-radius:50%; border:1px solid ${CYAN}; animation: jv-pulse 2s ease-out infinite; pointer-events:none; }
        .jv-input::placeholder { color: rgba(142,245,255,0.4); }
      `}</style>

      {/* ===== BLACK STAINED-GLASS SLAB ===== */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          pointerEvents: "none",
          zIndex: 0,
        }}
      >
        <motion.div
          initial={false}
          animate={{ width: slabW, height: slabH, borderRadius: isMinimized ? 44 : 40 }}
          transition={{ duration: dur, ease }}
          style={{
            position: "relative",
            overflow: "hidden",
            background: `
              linear-gradient(135deg, rgba(34,229,255,0.07) 0%, transparent 30%),
              linear-gradient(225deg, rgba(139,92,255,0.10) 0%, transparent 34%),
              radial-gradient(120% 80% at 50% 0%, rgba(255,255,255,0.07) 0%, transparent 55%),
              #05070b`,
            boxShadow:
              "inset 0 0 0 1px rgba(255,255,255,0.09), inset 0 1px 0 rgba(255,255,255,0.22), inset 0 -50px 90px rgba(0,0,0,0.7), inset 0 0 70px rgba(34,229,255,0.05), 0 30px 80px rgba(0,0,0,0.9)",
          }}
        >
          {/* leaded stained-glass facets */}
          <svg
            viewBox="0 0 100 100"
            preserveAspectRatio="none"
            style={{ position: "absolute", inset: 0, width: "100%", height: "100%" }}
          >
            <polygon points="0,0 38,0 0,34" fill="rgba(34,229,255,0.05)" />
            <polygon points="100,0 62,0 100,40" fill="rgba(139,92,255,0.07)" />
            <polygon points="0,100 0,66 30,100" fill="rgba(139,92,255,0.06)" />
            <polygon points="100,100 70,100 100,62" fill="rgba(34,229,255,0.05)" />
            <polygon points="38,0 62,0 50,22" fill="rgba(255,255,255,0.03)" />
            <path
              d="M0 34 L38 0 M100 40 L62 0 M0 66 L30 100 M100 62 L70 100 M38 0 L50 22 L62 0 M50 22 L50 38"
              stroke="rgba(160,230,255,0.13)"
              strokeWidth="1"
              fill="none"
              vectorEffect="non-scaling-stroke"
            />
          </svg>

          {/* moving specular sheen */}
          <div
            style={{
              position: "absolute",
              top: 0,
              bottom: 0,
              left: 0,
              width: "22%",
              background: "linear-gradient(90deg, transparent, rgba(255,255,255,0.06), transparent)",
              animation: "jv-sheen 9s linear infinite",
            }}
          />

          {/* ambient glow (cross-fades cyan/orange with state) */}
          {[CYAN, ORANGE].map((c) => (
            <div
              key={c}
              style={{
                position: "absolute",
                left: "50%",
                top: "50%",
                width: 760,
                height: 760,
                marginLeft: -380,
                marginTop: -380,
                borderRadius: "50%",
                background: `radial-gradient(circle, ${c}24 0%, transparent 62%)`,
                opacity: !isMinimized && accent === c ? 1 : 0,
                transition: "opacity 1s ease",
              }}
            />
          ))}
        </motion.div>
      </div>

      {/* THE MODEL: one canvas, shrinks in place (Python glides the window to the corner) */}
      <motion.div
        initial={false}
        animate={
          isMinimized
            ? { scale: miniScale, x: 0, y: 0, opacity: isSilent ? 0.4 : 1 }
            : { scale: 1, x: 0, y: 0, opacity: 1 }
        }
        whileHover={isMinimized ? { scale: miniScale * 1.12 } : undefined}
        transition={{ duration: dur, ease }}
        onClick={() => isMinimized && wake()}
        onHoverStart={() => setMiniHover(true)}
        onHoverEnd={() => setMiniHover(false)}
        style={{
          position: "relative",
          width: S,
          height: S,
          flexShrink: 0,
          cursor: isMinimized ? "pointer" : "default",
          zIndex: 10,
        }}
      >
        <div style={{ position: "absolute", inset: 0 }}>
          <Canvas camera={{ position: [0, 0, 6], fov: 50 }} dpr={[1, 2]} style={{ width: "100%", height: "100%" }}>
            <Hologram state={hologramState} isMinimized={isMinimized} hoveredButton={isMinimized ? null : hoveredButton} />
          </Canvas>
        </div>

        {/* centre status text, above the particles */}
        <AnimatePresence>
          {!isMinimized && (
            <motion.div
              key="status"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0, transition: { duration: 0.15 } }}
              transition={{ delay: 0.5, duration: 0.5 }}
              style={{
                position: "absolute",
                inset: 0,
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                justifyContent: "center",
                pointerEvents: "none",
                zIndex: 20,
              }}
            >
              <div
                style={{
                  position: "absolute",
                  width: 360,
                  height: 160,
                  background: "radial-gradient(ellipse, rgba(0,0,0,0.8) 0%, rgba(0,0,0,0.4) 50%, transparent 75%)",
                }}
              />
              <div style={{ position: "relative", display: "flex", flexDirection: "column", alignItems: "center", gap: 14 }}>
                <h1
                  style={{
                    margin: 0,
                    fontSize: 26,
                    fontWeight: 700,
                    letterSpacing: "0.4em",
                    paddingLeft: "0.4em",
                    fontFamily: MONO,
                    color: accent,
                    textShadow: `0 0 8px ${accent}, 0 0 22px ${accent}, 0 0 48px ${accent}88, 0 2px 4px #000`,
                    transition: "color 0.5s, text-shadow 0.5s",
                  }}
                >
                  {statusLabel}
                </h1>

                <div style={{ display: "flex", alignItems: "center", gap: 5, height: 26 }}>
                  {[0, 1, 2, 3, 4, 5, 6].map((i) => (
                    <span
                      key={i}
                      style={{
                        width: 3,
                        height: "100%",
                        borderRadius: 2,
                        background: accent,
                        boxShadow: `0 0 8px ${accent}`,
                        transformOrigin: "center",
                        transform: "scaleY(0.2)",
                        opacity: statusLabel === "STANDBY" ? 0.35 : 1,
                        animation:
                          statusLabel === "STANDBY"
                            ? "none"
                            : `jv-eq ${isProcessing ? 0.5 : 1.1}s ease-in-out ${i * 0.09}s infinite`,
                      }}
                    />
                  ))}
                </div>

                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 8,
                    fontSize: 10,
                    letterSpacing: "0.26em",
                    fontFamily: MONO,
                    color: "rgba(210,250,255,0.75)",
                    textShadow: "0 0 6px #000",
                    whiteSpace: "nowrap",
                  }}
                >
                  <span
                    style={{
                      width: 6,
                      height: 6,
                      borderRadius: "50%",
                      background: accent,
                      boxShadow: `0 0 10px ${accent}`,
                      animation: "jv-blink 1.6s ease-in-out infinite",
                    }}
                  />
                  {(isTextMode ? "TEXT" : "VOICE") + " LINK · " + engineShown.toUpperCase() + (memoryOn ? " · MEMORY ON" : "")}
                </div>
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {/* 4 orbiting buttons */}
        <AnimatePresence>
          {!isMinimized &&
            buttons.map((btn, i) => {
              const rad = (btn.angle * Math.PI) / 180;
              const x = Math.cos(rad) * radius;
              const y = Math.sin(rad) * radius;
              return (
                <motion.div
                  key={btn.id}
                  initial={{ opacity: 0, scale: 0.4 }}
                  animate={{ opacity: 1, scale: 1, transition: { delay: 0.5 + i * 0.07 } }}
                  exit={{ opacity: 0, scale: 0.4, transition: { duration: 0.15 } }}
                  onMouseEnter={() => setHoveredButton(btn.id)}
                  onMouseLeave={() => setHoveredButton(null)}
                  style={{
                    position: "absolute",
                    left: S / 2 + x - 32,
                    top: S / 2 + y - 32,
                    zIndex: 30,
                  }}
                >
                  <IconButton
                    icon={btn.icon}
                    label={btn.label}
                    onClick={btn.onClick}
                    active={btn.active}
                    hovered={hoveredButton === btn.id}
                    side={btn.side}
                    badge={(btn as any).badge}
                    badgeOn={(btn as any).badgeOn}
                  />
                </motion.div>
              );
            })}
        </AnimatePresence>

        {/* ENGINE PICKER */}
        <AnimatePresence>
          {showEngine && !isMinimized && (
            <motion.div
              initial={{ opacity: 0, y: -8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
              style={{
                position: "absolute",
                left: S / 2 - radius - 90,
                top: S / 2 + 56,
                width: 180,
                zIndex: 40,
                padding: 12,
                borderRadius: 14,
                background: "rgba(2,5,8,0.92)",
                backdropFilter: "blur(16px)",
                WebkitBackdropFilter: "blur(16px)",
                border: "1px solid rgba(34,229,255,0.3)",
                boxShadow: "0 0 24px rgba(34,229,255,0.15), inset 0 1px 0 rgba(255,255,255,0.1)",
                fontFamily: MONO,
              }}
            >
              <div style={{ fontSize: 9, letterSpacing: "0.2em", color: "#7d97a0", marginBottom: 4 }}>IN USE NOW</div>
              <div style={{ fontSize: 12, color: CYAN, marginBottom: 10, textShadow: `0 0 8px ${CYAN}` }}>
                {engineShown.toUpperCase()}
                {modelShort ? ` · ${modelShort}` : ""}
              </div>
              {["Auto", "Gemini", "Groq", "Ollama"].map((m) => (
                <button
                  key={m}
                  onClick={() => pickEngine(m)}
                  style={{
                    width: "100%",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    padding: "7px 10px",
                    marginBottom: 4,
                    borderRadius: 8,
                    cursor: "pointer",
                    fontFamily: MONO,
                    fontSize: 11,
                    letterSpacing: "0.12em",
                    textTransform: "uppercase",
                    color: engine.mode === m ? "#e9fdff" : "#9fc3cc",
                    background: engine.mode === m ? "rgba(34,229,255,0.16)" : "rgba(255,255,255,0.04)",
                    border: `1px solid ${engine.mode === m ? CYAN : "rgba(255,255,255,0.08)"}`,
                  }}
                >
                  {m}
                  {engine.mode === m && <span style={{ color: CYAN }}>●</span>}
                </button>
              ))}
            </motion.div>
          )}
        </AnimatePresence>
      </motion.div>

      {/* MINIMIZE button: top-right (only when maximized) */}
      <AnimatePresence>
        {!isMinimized && (
          <motion.button
            key="min-btn"
            initial={{ opacity: 0, scale: 0.6 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.6 }}
            whileHover={{ scale: 1.1 }}
            onClick={minimize}
            style={glassBtn}
            aria-label="Minimize"
          >
            <Minimize2 size={22} />
          </motion.button>
        )}
      </AnimatePresence>

      {/* orb ring + maximize hint (only when minimized) */}
      <div
        style={{
          position: "fixed",
          left: "50%",
          top: "50%",
          marginLeft: -MINI / 2,
          marginTop: -MINI / 2,
          width: MINI,
          height: MINI,
          borderRadius: "50%",
          border: "1px solid rgba(34,229,255,0.28)",
          boxShadow: "0 0 30px rgba(34,229,255,0.2), inset 0 0 30px rgba(34,229,255,0.08)",
          display: "grid",
          placeItems: "center",
          pointerEvents: "none",
          zIndex: 40,
          opacity: isMinimized ? (isSilent ? 0.4 : 1) : 0,
          transition: "opacity 0.5s ease",
          transitionDelay: isMinimized ? "0.5s" : "0s",
        }}
      >
        <Maximize2
          size={26}
          style={{
            color: "#bff9ff",
            filter: "drop-shadow(0 0 8px #22e5ff)",
            opacity: isMinimized && miniHover ? 1 : 0,
            transition: "opacity 0.3s",
          }}
        />
      </div>

      {/* TEXT MODE PANEL */}
      <AnimatePresence>
        {isTextMode && !isMinimized && (
          <div
            style={{
              position: "fixed",
              bottom: 36,
              left: 0,
              right: 0,
              display: "flex",
              justifyContent: "center",
              pointerEvents: "none",
              zIndex: 100,
            }}
          >
            <motion.div
              initial={{ opacity: 0, y: 30 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: 30 }}
              style={{
                width: Math.min(520, vp.w - 56),
                height: 230,
                display: "flex",
                flexDirection: "column",
                padding: 20,
                borderRadius: 18,
                pointerEvents: "auto",
                background: "rgba(2,5,8,0.82)",
                backdropFilter: "blur(20px)",
                WebkitBackdropFilter: "blur(20px)",
                border: "1px solid rgba(34,229,255,0.3)",
                boxShadow: "0 0 30px rgba(34,229,255,0.12), inset 0 1px 0 rgba(255,255,255,0.1)",
                fontFamily: MONO,
              }}
            >
              <div style={{ flex: 1, overflowY: "auto", fontSize: 13, color: "rgba(200,250,255,0.85)" }}>
                {messages.map((m, i) => (
                  <p key={i} style={{ margin: "0 0 10px" }}>
                    <span style={{ color: m.from === "jarvis" ? CYAN : ORANGE, fontWeight: 700 }}>
                      {m.from === "jarvis" ? "Jarvis:" : "You:"}
                    </span>{" "}
                    {m.text}
                  </p>
                ))}
                <div ref={chatEndRef} />
              </div>
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 10,
                  marginTop: 12,
                  paddingTop: 12,
                  borderTop: "1px solid rgba(34,229,255,0.3)",
                }}
              >
                <input
                  className="jv-input"
                  type="text"
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && sendMessage()}
                  placeholder="Type command, Sir..."
                  style={{
                    flex: 1,
                    background: "transparent",
                    border: "none",
                    outline: "none",
                    color: "#d4fbff",
                    fontSize: 14,
                    fontFamily: "inherit",
                  }}
                />
                <button
                  onClick={sendMessage}
                  style={{
                    background: "none",
                    border: "none",
                    cursor: "pointer",
                    color: CYAN,
                    display: "grid",
                    placeItems: "center",
                    padding: 4,
                  }}
                  aria-label="Send"
                >
                  <SendHorizontal size={20} />
                </button>
              </div>
            </motion.div>
          </div>
        )}
      </AnimatePresence>
    </div>
  );
}