"use client";
import { useState, useRef, useMemo, useEffect } from "react";
import type { ReactNode } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Mic, MessageSquare, History, Cpu, Minimize2, Maximize2, SendHorizontal } from "lucide-react";
import { Canvas, useFrame } from "@react-three/fiber";
import { Line } from "@react-three/drei";
import * as THREE from "three";

const CYAN = "#22e5ff";
const ORANGE = "#ff9a3c";

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
          color="#00ffff"
          lineWidth={1}
          transparent
          opacity={line.opacity * 0.3}
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

    const colorCyan = new THREE.Color("#00ffff");
    const colorWhite = new THREE.Color("#ffffff");
    const colorBlue = new THREE.Color("#0066ff");

    for (let i = 0; i < count; i++) {
      const r = 1.1 + Math.random() * 0.5;
      const theta = 2 * Math.PI * Math.random();
      const phi = Math.acos(2 * Math.random() - 1);
      const noise = Math.sin(theta * 15) * Math.cos(phi * 15) * 0.2;

      pos[i * 3] = (r + noise) * Math.sin(phi) * Math.cos(theta);
      pos[i * 3 + 1] = (r + noise) * Math.sin(phi) * Math.sin(theta);
      pos[i * 3 + 2] = (r + noise) * Math.cos(phi);

      const rand = Math.random();
      const c = rand < 0.6 ? colorCyan : rand < 0.9 ? colorWhite : colorBlue;
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

// --- ICON BUTTON ---
function IconButton({
  icon,
  label,
  onClick,
  active,
  hovered,
  side,
}: {
  icon: ReactNode;
  label: string;
  onClick?: () => void;
  active: boolean;
  hovered: boolean;
  side: "top" | "bottom" | "left" | "right";
}) {
  const labelPos: React.CSSProperties =
    side === "top"
      ? { bottom: "100%", left: "50%", transform: "translateX(-50%)", marginBottom: 14 }
      : side === "bottom"
      ? { top: "100%", left: "50%", transform: "translateX(-50%)", marginTop: 14 }
      : side === "left"
      ? { right: "100%", top: "50%", transform: "translateY(-50%)", marginRight: 14 }
      : { left: "100%", top: "50%", transform: "translateY(-50%)", marginLeft: 14 };

  const style: React.CSSProperties = {
    position: "relative",
    width: 64,
    height: 64,
    padding: 0,
    borderRadius: "50%",
    display: "grid",
    placeItems: "center",
    cursor: "pointer",
    outline: "none",
    backdropFilter: "blur(14px)",
    WebkitBackdropFilter: "blur(14px)",
    transition: "all 0.3s ease",
    transform: hovered ? "scale(1.1)" : "scale(1)",
    ...(active
      ? {
          background: "rgba(34,229,255,0.16)",
          border: "1px solid rgba(34,229,255,0.9)",
          color: "#8ef5ff",
          boxShadow: "0 0 22px rgba(34,229,255,0.45), inset 0 0 14px rgba(34,229,255,0.2)",
        }
      : hovered
      ? {
          background: "rgba(34,229,255,0.1)",
          border: "1px solid rgba(34,229,255,0.6)",
          color: "#c4faff",
          boxShadow: "0 0 18px rgba(34,229,255,0.3)",
        }
      : {
          background: "rgba(255,255,255,0.05)",
          border: "1px solid rgba(255,255,255,0.14)",
          color: "#8fb8c2",
          boxShadow: "0 0 0 rgba(0,0,0,0)",
        }),
  };

  return (
    <div style={{ position: "relative" }}>
      {active && <span className="jv-ring" />}
      <button onClick={onClick} style={style} aria-label={label}>
        <span
          style={{
            position: "absolute",
            inset: 0,
            borderRadius: "50%",
            background: "linear-gradient(to bottom, rgba(255,255,255,0.12), transparent)",
            pointerEvents: "none",
          }}
        />
        <span style={{ position: "relative", display: "grid", placeItems: "center" }}>{icon}</span>
      </button>
      <div
        style={{
          position: "absolute",
          ...labelPos,
          padding: "5px 12px",
          background: "rgba(0,0,0,0.9)",
          color: "#8ef5ff",
          fontSize: 10,
          letterSpacing: "0.18em",
          textTransform: "uppercase",
          fontFamily: "ui-monospace, monospace",
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

  useEffect(() => {
    const handleStateChange = (event: Event) => {
      const state = (event as CustomEvent).detail;
      if (state === "listening") {
        setIsListening(true);
        setIsProcessing(false);
      } else if (state === "processing" || state === "speaking") {
        setIsListening(false);
        setIsProcessing(true);
      } else if (state === "standby") {
        setIsListening(false);
        setIsProcessing(false);
      } else if (state === "minimized") {
        setIsMinimized(true);
      } else if (state === "maximized") {
        setIsMinimized(false);
      }
    };
    window.addEventListener("jarvisState", handleStateChange);
    return () => window.removeEventListener("jarvisState", handleStateChange);
  }, []);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const sendMessage = () => {
    const text = input.trim();
    if (!text) return;
    setMessages((m) => [...m, { from: "you", text }]);
    setInput("");
    window.dispatchEvent(new CustomEvent("jarvisCommand", { detail: text }));
  };

  const hologramState = isProcessing ? "speaking" : isListening ? "listening" : "standby";
  const accent = isProcessing ? ORANGE : CYAN;
  const statusLabel = isProcessing ? "PROCESSING" : isListening ? "LISTENING" : "STANDBY";

  const S = Math.max(150, Math.min(700, vp.w - 24, vp.h - 24));
  const MINI = 150;
  const MARGIN = 28;
  const miniScale = MINI / S;
  const miniX = vp.w / 2 - MARGIN - MINI / 2;
  const miniY = vp.h / 2 - MARGIN - MINI / 2;
  const radius = S * 0.37;

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
    { id: "memory", icon: <History size={24} />, label: "Memory", active: false, angle: 90, side: "bottom" as const },
    { id: "engine", icon: <Cpu size={24} />, label: "Engine", active: false, angle: 180, side: "left" as const },
  ];

  const glassBtn: React.CSSProperties = {
    position: "fixed",
    top: 24,
    right: 24,
    zIndex: 100,
    width: 52,
    height: 52,
    borderRadius: "50%",
    display: "grid",
    placeItems: "center",
    cursor: "pointer",
    color: "#8ef5ff",
    background: "rgba(255,255,255,0.06)",
    border: "1px solid rgba(34,229,255,0.35)",
    backdropFilter: "blur(14px)",
    WebkitBackdropFilter: "blur(14px)",
    boxShadow: "0 0 18px rgba(34,229,255,0.2)",
    padding: 0,
  };

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        background: "transparent",
        overflow: "hidden",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        pointerEvents: isMinimized ? "none" : "auto",
      }}
    >
      <style>{`
        @keyframes jv-eq { 0%,100% { transform: scaleY(0.25); } 50% { transform: scaleY(1); } }
        @keyframes jv-pulse { 0% { transform: scale(1); opacity: .7; } 100% { transform: scale(1.55); opacity: 0; } }
        @keyframes jv-blink { 0%,100% { opacity: 1; } 50% { opacity: .35; } }
        .jv-ring { position:absolute; inset:0; border-radius:50%; border:1px solid ${CYAN}; animation: jv-pulse 2s ease-out infinite; pointer-events:none; }
        .jv-input::placeholder { color: rgba(142,245,255,0.4); }
      `}</style>

      {[CYAN, ORANGE].map((c) => (
        <div
          key={c}
          style={{
            position: "absolute",
            width: 760,
            height: 760,
            borderRadius: "50%",
            pointerEvents: "none",
            background: `radial-gradient(circle, ${c}22 0%, transparent 65%)`,
            opacity: !isMinimized && accent === c ? 1 : 0,
            transition: "opacity 1s ease",
          }}
        />
      ))}

      <motion.div
        initial={false}
        animate={
          isMinimized
            ? { scale: miniScale, x: miniX, y: miniY }
            : { scale: 1, x: 0, y: 0 }
        }
        whileHover={isMinimized ? { scale: miniScale * 1.12 } : undefined}
        transition={{ duration: 0.8, ease: [0.65, 0, 0.35, 1] }}
        onClick={() => isMinimized && setIsMinimized(false)}
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
          <Canvas 
            camera={{ position: [0, 0, 6], fov: 50 }} 
            dpr={[1, 2]} 
            gl={{ alpha: true, antialias: true, preserveDrawingBuffer: true }} 
            onCreated={({ gl }) => gl.setClearColor(0x000000, 0)}               
            style={{ width: "100%", height: "100%", background: "transparent" }}
          >
            <Hologram state={hologramState} isMinimized={isMinimized} hoveredButton={isMinimized ? null : hoveredButton} />
          </Canvas>
        </div>

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
                  width: 340,
                  height: 150,
                  background: "radial-gradient(ellipse, rgba(0,0,0,0.75) 0%, rgba(0,0,0,0.35) 50%, transparent 75%)",
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
                    fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
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
                    letterSpacing: "0.3em",
                    fontFamily: "ui-monospace, monospace",
                    color: "rgba(200,250,255,0.7)",
                    textShadow: "0 0 6px #000",
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
                  {isTextMode ? "TEXT LINK ONLINE" : "VOICE LINK ONLINE"}
                </div>
              </div>
            </motion.div>
          )}
        </AnimatePresence>

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
                  />
                </motion.div>
              );
            })}
        </AnimatePresence>
      </motion.div>

      <AnimatePresence>
        {!isMinimized && (
          <motion.button
            key="min-btn"
            initial={{ opacity: 0, scale: 0.6 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.6 }}
            whileHover={{ scale: 1.1 }}
            onClick={() => {
              setIsMinimized(true);
              setHoveredButton(null);
            }}
            style={glassBtn}
            aria-label="Minimize"
          >
            <Minimize2 size={22} />
          </motion.button>
        )}
      </AnimatePresence>

      <div
        style={{
          position: "fixed",
          right: MARGIN,
          bottom: MARGIN,
          width: MINI,
          height: MINI,
          borderRadius: "50%",
          border: "1px solid rgba(34,229,255,0.25)",
          boxShadow: "0 0 30px rgba(34,229,255,0.2), inset 0 0 30px rgba(34,229,255,0.08)",
          display: "grid",
          placeItems: "center",
          pointerEvents: "none",
          zIndex: 40,
          opacity: isMinimized ? 1 : 0,
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

      <AnimatePresence>
        {isTextMode && !isMinimized && (
          <div
            style={{
              position: "fixed",
              bottom: 32,
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
                width: Math.min(520, vp.w - 32),
                height: 230,
                display: "flex",
                flexDirection: "column",
                padding: 20,
                borderRadius: 18,
                pointerEvents: "auto",
                background: "rgba(0,0,0,0.65)",
                backdropFilter: "blur(20px)",
                WebkitBackdropFilter: "blur(20px)",
                border: "1px solid rgba(34,229,255,0.3)",
                boxShadow: "0 0 30px rgba(34,229,255,0.12)",
                fontFamily: "ui-monospace, monospace",
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