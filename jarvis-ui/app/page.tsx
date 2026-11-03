"use client";

import { useState, useRef, useMemo, useEffect } from "react";
import type { ReactNode, CSSProperties } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Mic, MicOff, MessageSquare, History, Cpu, Minimize2, Maximize2, SendHorizontal, X } from "lucide-react";
import { Canvas, useFrame } from "@react-three/fiber";
import * as THREE from "three";
import "./jarvis-glass.css";

const CYAN = "#22e5ff";
const ORANGE = "#ff9a3c";
const VIOLET = "#8b5cff";
const RED = "#ff5470";
const MONO = "ui-monospace, SFMono-Regular, Menlo, monospace";

type Msg = { id: number; from: "jarvis" | "you"; text: string };
type ControlButton = {
  id: string;
  icon: ReactNode;
  label: string;
  onClick: () => void;
  active: boolean;
  angle: number;
  side: "top" | "bottom" | "left" | "right";
  badge?: string;
  badgeOn?: boolean;
  redTint?: boolean;
};

declare global {
  interface Window {
    __handPinching?: boolean;
    __jarvisLinked?: boolean;
    __jarvisMinimized?: boolean;
  }
}

function Hologram({
  hoveredButton,
}: {
  hoveredButton: string | null;
}) {
  const outerRef = useRef<THREE.Group>(null);
  const groupRef = useRef<THREE.Group>(null);

  const [positions, colors] = useMemo(() => {
    const count = 8000;
    const pos = new Float32Array(count * 3);
    const cols = new Float32Array(count * 3);

    const colorCyan = new THREE.Color("#22e5ff");
    const colorWhite = new THREE.Color("#ffffff");
    const colorViolet = new THREE.Color(VIOLET);
    const sample = (value: number) => {
      const result = Math.sin(value * 12.9898 + 78.233) * 43758.5453;
      return result - Math.floor(result);
    };

    for (let i = 0; i < count; i++) {
      const r = 1.1 + sample(i * 4) * 0.5;
      const theta = 2 * Math.PI * sample(i * 4 + 1);
      const phi = Math.acos(2 * sample(i * 4 + 2) - 1);
      const noise = Math.sin(theta * 15) * Math.cos(phi * 15) * 0.2;

      pos[i * 3] = (r + noise) * Math.sin(phi) * Math.cos(theta);
      pos[i * 3 + 1] = (r + noise) * Math.sin(phi) * Math.sin(theta);
      pos[i * 3 + 2] = (r + noise) * Math.cos(phi);

      const rand = sample(i * 4 + 3);
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
  const materialRef = useRef(customMaterial);

  useFrame((frame, delta) => {
    if (!groupRef.current || !outerRef.current) return;
    const t = frame.clock.elapsedTime;
    const frameDelta = Math.min(delta, 0.1);
    const rotationEase = 1 - Math.exp(-frameDelta * 12);
    const positionEase = 1 - Math.exp(-frameDelta * 10);
    const effectEase = 1 - Math.exp(-frameDelta * 10);

    const css = document.documentElement.style;
    const hs = THREE.MathUtils.clamp(parseFloat(css.getPropertyValue("--hand-scale")) || 1, 0.5, 2.4);
    const hx = THREE.MathUtils.clamp(parseFloat(css.getPropertyValue("--hand-x")) || 0, -1, 1);
    const hy = THREE.MathUtils.clamp(parseFloat(css.getPropertyValue("--hand-y")) || 0, -1, 1);
    const pinching = !!window.__handPinching;

    const currentScale = outerRef.current.scale.x;
    const targetScale = THREE.MathUtils.lerp(currentScale, hs, rotationEase);
    outerRef.current.scale.setScalar(targetScale);

    if (pinching) {
      groupRef.current.rotation.y = THREE.MathUtils.lerp(groupRef.current.rotation.y, hx * 0.85, rotationEase);
      groupRef.current.rotation.x = THREE.MathUtils.lerp(groupRef.current.rotation.x, -hy * 0.65, rotationEase);
      outerRef.current.position.x = THREE.MathUtils.lerp(outerRef.current.position.x, hx * 0.55, positionEase);
      outerRef.current.position.y = THREE.MathUtils.lerp(outerRef.current.position.y, -hy * 0.4, positionEase);
    } else {
      outerRef.current.position.x = THREE.MathUtils.lerp(outerRef.current.position.x, 0, positionEase);
      outerRef.current.position.y = THREE.MathUtils.lerp(outerRef.current.position.y, 0, positionEase);
      groupRef.current.rotation.x += frameDelta * 0.08;
      groupRef.current.rotation.y += frameDelta * 0.12;
      groupRef.current.rotation.z = Math.sin(t * 0.3) * 0.1;
    }

    const u = materialRef.current.uniforms;
    let strength = 0;
    if (hoveredButton) {
      const targetDir = new THREE.Vector3();
      if (hoveredButton === "text") targetDir.set(0, 1, 0);
      if (hoveredButton === "voice") targetDir.set(1, 0, 0);
      if (hoveredButton === "memory") targetDir.set(0, -1, 0);
      if (hoveredButton === "engine") targetDir.set(-1, 0, 0);
      const inverseRotation = new THREE.Quaternion().copy(groupRef.current.quaternion).invert();
      targetDir.applyQuaternion(inverseRotation);
      u.uBulgeDir.value.lerp(targetDir, effectEase);
      strength = 1.0;
    }
    u.uBulgeStrength.value = THREE.MathUtils.lerp(u.uBulgeStrength.value, strength, effectEase);
  });

  return (
    <group ref={outerRef}>
      <group ref={groupRef}>
        <points>
          <bufferGeometry>
            <bufferAttribute attach="attributes-position" args={[positions, 3]} />
            <bufferAttribute attach="attributes-color" args={[colors, 3]} />
          </bufferGeometry>
          <primitive object={customMaterial} attach="material" />
        </points>
      </group>
    </group>
  );
}

function IconButton({
  icon,
  label,
  onClick,
  active,
  hovered,
  side,
  badge,
  badgeOn,
  redTint,
}: {
  icon: ReactNode;
  label: string;
  onClick?: () => void;
  active: boolean;
  hovered: boolean;
  side: "top" | "bottom" | "left" | "right";
  badge?: string;
  badgeOn?: boolean;
  redTint?: boolean;
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
        background: redTint
          ? "radial-gradient(circle at 30% 22%, rgba(255,190,190,0.5), rgba(255,84,112,0.16) 52%, rgba(28,0,5,0.75) 100%)"
          : "radial-gradient(circle at 30% 22%, rgba(190,250,255,0.5), rgba(34,229,255,0.16) 52%, rgba(0,18,28,0.75) 100%)",
        color: "#e9fdff",
        boxShadow: `${inset}, 0 0 0 1px ${redTint ? RED : CYAN}, 0 0 28px ${redTint ? "rgba(255,84,112,0.55)" : "rgba(34,229,255,0.55)"}, 0 10px 22px rgba(0,0,0,0.8)`,
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
      {active && <span className="jv-ring" style={{ borderColor: redTint ? RED : CYAN }} />}
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
            border: `1px solid ${badgeOn ? (redTint ? RED : CYAN) : "rgba(255,255,255,0.18)"}`,
            color: badgeOn ? (redTint ? RED : CYAN) : "#7d97a0",
            boxShadow: badgeOn ? `0 0 10px ${redTint ? "rgba(255,84,112,0.35)" : "rgba(34,229,255,0.35)"}` : "none",
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

function Bracket({ pos, color }: { pos: "tl" | "tr" | "bl" | "br"; color: string }) {
  const s: CSSProperties = {
    position: "absolute",
    width: 26,
    height: 26,
    borderColor: color,
    borderStyle: "solid",
    borderWidth: 0,
    opacity: 0.55,
    transition: "border-color 0.5s",
  };
  if (pos === "tl") Object.assign(s, { top: 22, left: 22, borderTopWidth: 2, borderLeftWidth: 2, borderTopLeftRadius: 10 });
  if (pos === "tr") Object.assign(s, { top: 22, right: 22, borderTopWidth: 2, borderRightWidth: 2, borderTopRightRadius: 10 });
  if (pos === "bl") Object.assign(s, { bottom: 22, left: 22, borderBottomWidth: 2, borderLeftWidth: 2, borderBottomLeftRadius: 10 });
  if (pos === "br") Object.assign(s, { bottom: 22, right: 22, borderBottomWidth: 2, borderRightWidth: 2, borderBottomRightRadius: 10 });
  return <div style={s} />;
}

export default function JarvisUI() {
  const [isListening, setIsListening] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [isOnline, setIsOnline] = useState(true);
  const [isTextMode, setIsTextMode] = useState(false);
  const [isMinimized, setIsMinimized] = useState(false);
  const [isSilent, setIsSilent] = useState(false);
  const [memoryOn, setMemoryOn] = useState(false);
  const [engine, setEngine] = useState({ mode: "Auto", name: "Auto", model: "" });
  const [showEngine, setShowEngine] = useState(false);
  const [hoveredButton, setHoveredButton] = useState<string | null>(null);
  const [vp, setVp] = useState({ w: 1280, h: 800 });
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [visionMessage, setVisionMessage] = useState("HAND TRACKING · MAXIMIZE TO ENABLE");
  const chatEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const update = () => setVp({ w: window.innerWidth, h: window.innerHeight });
    update();
    window.addEventListener("resize", update);
    return () => window.removeEventListener("resize", update);
  }, []);

  useEffect(() => {
    const h = (e: Event) => {
      const d = (e as CustomEvent).detail;
      const s = typeof d === "string" ? { state: d } : d;
      if (typeof s.mini === "boolean") window.__jarvisMinimized = s.mini;
      if (s.state === "listening") {
        setIsListening(true);
        setIsProcessing(false);
        setIsSpeaking(false);
      } else if (s.state === "processing") {
        setIsListening(false);
        setIsProcessing(true);
        setIsSpeaking(false);
      } else if (s.state === "speaking") {
        setIsListening(false);
        setIsProcessing(false);
        setIsSpeaking(true);
      } else if (s.state === "standby") {
        setIsListening(false);
        setIsProcessing(false);
        setIsSpeaking(false);
      }
      if (typeof s.mini === "boolean") {
        setIsMinimized(s.mini);
        if (s.mini) {
          setHoveredButton(null);
          setShowEngine(false);
        }
      }
      if (typeof s.silent === "boolean") setIsSilent(s.silent);
      if (typeof s.online === "boolean") setIsOnline(s.online);
      if (typeof s.memory === "boolean") setMemoryOn(s.memory);
      if (typeof s.text_mode === "boolean") setIsTextMode(s.text_mode);
      if (s.engine) setEngine(s.engine);
    };
    window.addEventListener("jarvisState", h);
    return () => window.removeEventListener("jarvisState", h);
  }, []);

  useEffect(() => {
    const h = (e: Event) => {
      const { status, message } = (e as CustomEvent<{ status: string; message?: string }>).detail;
      setVisionMessage(message || status);
    };
    window.addEventListener("jarvisVisionStatus", h);
    return () => window.removeEventListener("jarvisVisionStatus", h);
  }, []);

  useEffect(() => {
    const h = (e: Event) => {
      const m = (e as CustomEvent).detail as Msg;
      setMessages((prev) => {
        const i = prev.findIndex((x) => x.id === m.id);
        const item: Msg = { id: m.id, from: m.from, text: m.text };
        if (i >= 0) {
          const next = [...prev];
          next[i] = item;
          return next;
        }
        return [...prev, item].slice(-80);
      });
    };
    window.addEventListener("jarvisChat", h);
    return () => window.removeEventListener("jarvisChat", h);
  }, []);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isProcessing]);

  const act = (o: object) => window.dispatchEvent(new CustomEvent("jarvisAction", { detail: o }));
  const linked = () => !!window.__jarvisLinked;
  const wake = () => {
    window.__jarvisMinimized = false;
    act({ action: "ui", do: "maximize" });
    if (!linked()) setIsMinimized(false);
  };
  const minimize = () => {
    window.__jarvisMinimized = true;
    act({ action: "ui", do: "minimize" });
    if (!linked()) {
      setIsMinimized(true);
      setShowEngine(false);
      setHoveredButton(null);
    }
  };
  const closeJarvis = () => act({ action: "ui", do: "close" });
  const setMode = (text: boolean) => {
    setIsTextMode(text);
    act({ action: "set_mode", text });
  };
  const toggleMute = () => {
    const nextMute = !isSilent;
    setIsSilent(nextMute);
    act({ action: "set_mute", muted: nextMute });
  };
  const toggleMemory = () => {
    const v = !memoryOn;
    setMemoryOn(v);
    act({ action: "set_memory", on: v });
  };
  const pickEngine = (m: string) => {
    act({ action: "set_engine", engine: m });
    setShowEngine(false);
  };
  const sendMessage = () => {
    const text = input.trim();
    if (!text) return;
    setInput("");
    window.dispatchEvent(new CustomEvent("jarvisCommand", { detail: text }));
    if (!linked()) setMessages((m) => [...m, { id: -Date.now(), from: "you", text }]);
  };

  const accent = !isOnline || isSilent ? RED : isSpeaking ? CYAN : isProcessing ? ORANGE : CYAN;
  
  const statusLabel = !isOnline 
    ? "OFFLINE" 
    : isSilent 
    ? "MIC MUTED · JARVIS IS DEAF" 
    : isSpeaking 
    ? "SPEAKING" 
    : isProcessing 
    ? "PROCESSING" 
    : isListening 
    ? "LISTENING" 
    : "STANDBY";

  const engineShown = engine.name && engine.name !== "—" ? engine.name : engine.mode;
  const modelShort = (engine.model || "").replace("openai/", "");
  const dim = !isOnline || isSilent;
  const lastIsYou = messages.length > 0 && messages[messages.length - 1].from === "you";

  const compact = vp.w < 320;
  const S = compact ? vp.w - 30 : Math.max(320, Math.min(vp.w, vp.h));
  const MINI = 170;
  const miniScale = compact ? 1 : MINI / S;
  const radius = S * 0.37;
  const ease = [0.65, 0, 0.35, 1] as const;
  const dur = 0.8;

  const buttons: ControlButton[] = [
    {
      id: "text",
      icon: <MessageSquare size={24} />,
      label: "Text Mode",
      onClick: () => setMode(!isTextMode),
      active: isTextMode,
      angle: -90,
      side: "top" as const,
    },
    {
      id: "voice",
      icon: isSilent ? <MicOff size={24} color={RED} /> : <Mic size={24} />,
      label: isSilent ? "Unmute Mic" : "Mute Mic",
      onClick: toggleMute,
      active: !isSilent,
      angle: 0,
      side: "right" as const,
      badge: isSilent ? "MUTED" : undefined,
      badgeOn: false,
      redTint: isSilent,
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
    top: 34,
    right: 34,
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
  const closeBtn: CSSProperties = {
    ...glassBtn,
    right: 92,
    color: "#ff9aaa",
  };

  const slabW = isMinimized ? 200 : "100vw";
  const slabH = isMinimized ? 200 : "100vh";

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        background: "radial-gradient(ellipse at 50% 45%, #0c202a 0%, #06111b 48%, #02060b 100%)",
        overflow: "hidden",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      <style>{`
        html, body { background: #000 !important; margin: 0; overflow: hidden; }
        @keyframes jv-eq { 0%,100% { transform: scaleY(0.25); } 50% { transform: scaleY(1); } }
        @keyframes jv-pulse { 0% { transform: scale(1); opacity: .7; } 100% { transform: scale(1.55); opacity: 0; } }
        @keyframes jv-blink { 0%,100% { opacity: 1; } 50% { opacity: .35; } }
        @keyframes jv-dot { 0%,80%,100% { opacity: .2; } 40% { opacity: 1; } }
        @keyframes jv-scan { from { background-position: 0 0; } to { background-position: 0 80px; } }
        .jv-ring { position:absolute; inset:0; border-radius:50%; border:1px solid ${CYAN}; animation: jv-pulse 2s ease-out infinite; pointer-events:none; }
        .jv-input::placeholder { color: rgba(142,245,255,0.4); }
        .jv-scroll::-webkit-scrollbar { width: 6px; }
        .jv-scroll::-webkit-scrollbar-thumb { background: rgba(34,229,255,0.25); border-radius: 3px; }
      `}</style>

      {/* INFINITE CLEAN GLASS SLAB */}
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
          animate={{ width: slabW, height: slabH, borderRadius: isMinimized ? 44 : 0 }}
          transition={{ duration: dur, ease }}
          style={{
            position: "relative",
            overflow: "hidden",
            background: `
              linear-gradient(115deg, rgba(255,255,255,0.08) 0%, transparent 28%, transparent 70%, rgba(34,229,255,0.08) 100%),
              radial-gradient(90% 60% at 10% 0%, rgba(34,229,255,0.12), transparent 60%),
              radial-gradient(80% 60% at 100% 100%, rgba(139,92,255,0.14), transparent 60%),
              linear-gradient(180deg, rgba(14,32,45,0.78) 0%, rgba(5,14,24,0.72) 55%, rgba(2,7,13,0.84) 100%)`,
            backdropFilter: "blur(32px) saturate(170%)",
            WebkitBackdropFilter: "blur(32px) saturate(170%)",
            boxShadow:
              "inset 0 0 0 1px rgba(255,255,255,0.08), inset 0 1px 0 rgba(255,255,255,0.2), inset 0 -60px 100px rgba(0,0,0,0.65)",
          }}
        >
          <div
            aria-hidden
            style={{
              position: "absolute",
              inset: "7% 9% 10% 9%",
              borderRadius: 28,
              overflow: "hidden",
              pointerEvents: "none",
              opacity: isMinimized ? 0 : 1,
              transition: "opacity .6s",
              background: "linear-gradient(145deg, rgba(255,255,255,0.10), rgba(34,229,255,0.04) 45%, rgba(255,255,255,0.03))",
              border: "1px solid rgba(34,229,255,0.35)",
              boxShadow: "inset 0 0 60px rgba(34,229,255,0.12), 0 0 40px rgba(34,229,255,0.12)",
              backdropFilter: "blur(10px) saturate(150%)",
              WebkitBackdropFilter: "blur(10px) saturate(150%)",
            }}
          >
            <div style={{ position: "absolute", inset: 0, background: "linear-gradient(115deg, transparent 30%, rgba(255,255,255,0.12) 45%, transparent 60%)" }} />
            <div style={{ position: "absolute", inset: 0, animation: "jv-scan 6s linear infinite", background: "repeating-linear-gradient(0deg, rgba(34,229,255,0.07) 0 1px, transparent 1px 4px)" }} />
          </div>

          <div
            aria-hidden
            style={{
              position: "absolute", left: "28%", width: "44%", bottom: "13%", height: "62%", pointerEvents: "none",
              opacity: isMinimized ? 0 : 0.5, transition: "opacity .6s", filter: "blur(6px)",
              clipPath: "polygon(25% 100%, 75% 100%, 100% 0, 0 0)",
              background: "linear-gradient(to top, rgba(34,229,255,0.4), transparent)"
            }}
          />

          <div
            aria-hidden
            style={{
              position: "absolute", left: "28%", width: "44%", bottom: "10%", height: "6%", borderRadius: "50%",
              pointerEvents: "none", opacity: isMinimized ? 0 : 1, transition: "opacity .6s",
              background: "radial-gradient(ellipse, rgba(34,229,255,0.9), rgba(34,229,255,0.15) 60%, transparent 70%)",
              boxShadow: "0 0 30px rgba(34,229,255,0.8)"
            }}
          />

          {[CYAN, ORANGE, RED].map((c) => (
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

          <div style={{ opacity: isMinimized ? 0 : 1, transition: "opacity 0.4s" }}>
            <Bracket pos="tl" color={accent} />
            <Bracket pos="tr" color={accent} />
            <Bracket pos="bl" color={accent} />
            <Bracket pos="br" color={accent} />
          </div>
        </motion.div>
      </div>

      {/* 3D CANVAS VIEWPORT */}
      <motion.div
        initial={false}
        animate={
          isMinimized
            ? { scale: miniScale, x: 0, y: 0, opacity: dim ? 0.4 : 1 }
            : { scale: 1, x: 0, y: 0, opacity: !isOnline ? 0.5 : 1 }
        }
        whileHover={isMinimized ? { scale: miniScale * 1.12 } : undefined}
        transition={{ duration: dur, ease }}
        onClick={() => isMinimized && wake()}
        style={{
          position: "relative",
          width: S,
          height: S,
          flexShrink: 0,
          cursor: isMinimized ? "pointer" : "default",
          zIndex: 10,
        }}
      >
        <div style={{ position: "absolute", inset: "-30%" }}>
          <Canvas
            camera={{ position: [0, 0, 6], fov: 73.5 }}
            dpr={[1, 2]}
            resize={{ offsetSize: true, scroll: false }}
            style={{ position: "absolute", inset: 0, width: "100%", height: "100%" }}
          >
            <ambientLight intensity={0.7} />
            <pointLight position={[10, 10, 10]} intensity={1.5} color={accent} />
            <Hologram hoveredButton={isMinimized ? null : hoveredButton} />
          </Canvas>
        </div>

        {/* CENTRAL STATUS TEXT */}
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
                  width: 420,
                  height: 180,
                  background: "radial-gradient(ellipse, rgba(0,0,0,0.85) 0%, rgba(0,0,0,0.4) 60%, transparent 80%)",
                }}
              />
              <div style={{ position: "relative", display: "flex", flexDirection: "column", alignItems: "center", gap: 14 }}>
                <h1
                  style={{
                    margin: 0,
                    fontSize: 24,
                    fontWeight: 700,
                    letterSpacing: "0.3em",
                    paddingLeft: "0.3em",
                    fontFamily: MONO,
                    color: accent,
                    textShadow: `0 0 8px ${accent}, 0 0 22px ${accent}, 0 0 48px ${accent}88, 0 2px 4px #000`,
                    transition: "color 0.5s, text-shadow 0.5s",
                    textAlign: "center",
                    whiteSpace: "nowrap",
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
                        opacity: statusLabel === "STANDBY" || statusLabel === "MIC MUTED · JARVIS IS DEAF" || !isOnline ? 0.35 : 1,
                        animation:
                          statusLabel === "STANDBY" || statusLabel === "MIC MUTED · JARVIS IS DEAF" || !isOnline
                            ? "none"
                            : `jv-eq ${isProcessing || isSpeaking ? 0.5 : 1.1}s ease-in-out ${i * 0.09}s infinite`,
                      }}
                    />
                  ))}
                </div>

                {!isMinimized && (
                  <div
                    style={{
                      maxWidth: 340,
                      padding: "6px 10px",
                      borderRadius: 999,
                      border: "1px solid rgba(34,229,255,0.2)",
                      background: "rgba(4,16,24,0.55)",
                      color: visionMessage.includes("ACTIVE") ? CYAN : "rgba(190,239,255,0.62)",
                      fontSize: 9,
                      letterSpacing: "0.12em",
                      fontFamily: MONO,
                      textAlign: "center",
                    }}
                  >
                    {visionMessage}
                  </div>
                )}

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
                  {!isOnline
                    ? "ALL SYSTEMS OFFLINE"
                    : isSilent
                    ? "STANDBY MODE"
                    : (isTextMode ? "TEXT" : "VOICE") + " LINK · " + engineShown.toUpperCase() + (memoryOn ? " · MEMORY ON" : "")}
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
                    badge={btn.badge}
                    badgeOn={btn.badgeOn}
                    redTint={btn.redTint}
                  />
                </motion.div>
              );
            })}
        </AnimatePresence>

        <AnimatePresence>
          {showEngine && !isMinimized && (
            <motion.div
              initial={{ opacity: 0, y: -8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
              style={{
                position: "absolute",
                left: Math.max(8, S / 2 - radius - 90),
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
      <AnimatePresence>
        {!isMinimized && (
          <motion.button
            key="close-btn"
            initial={{ opacity: 0, scale: 0.6 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.6 }}
            whileHover={{ scale: 1.1 }}
            onClick={closeJarvis}
            style={closeBtn}
            aria-label="Close Jarvis"
            title="Close Jarvis"
          >
            <X size={20} />
          </motion.button>
        )}
      </AnimatePresence>

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
          border: `1px solid ${!isOnline ? "rgba(255,84,112,0.4)" : "rgba(34,229,255,0.28)"}`,
          boxShadow: `0 0 30px ${!isOnline ? "rgba(255,84,112,0.2)" : "rgba(34,229,255,0.2)"}, inset 0 0 30px rgba(34,229,255,0.08)`,
          display: "grid",
          placeItems: "center",
          pointerEvents: "none",
          zIndex: 40,
          opacity: isMinimized ? (dim ? 0.4 : 1) : 0,
          transition: "opacity 0.5s ease",
          transitionDelay: isMinimized ? "0.5s" : "0s",
        }}
      />

      <AnimatePresence>
        {isMinimized && (
          <motion.div
            key="mini-window-controls"
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            style={{
              position: "fixed",
              left: "calc(50% - 38px)",
              top: `calc(50% - ${MINI / 2}px + 12px)`,
              display: "flex",
              gap: 8,
              zIndex: 110,
            }}
          >
            <button
              onClick={wake}
              aria-label="Maximize Jarvis"
              title="Maximize Jarvis"
              style={{ ...glassBtn, position: "static", width: 34, height: 34, background: "rgba(3,18,26,0.9)" }}
            >
              <Maximize2 size={16} />
            </button>
            <button
              onClick={closeJarvis}
              aria-label="Close Jarvis"
              title="Close Jarvis"
              style={{ ...closeBtn, position: "static", width: 34, height: 34, background: "rgba(24,7,13,0.92)" }}
            >
              <X size={16} />
            </button>
          </motion.div>
        )}
      </AnimatePresence>

      <AnimatePresence>
        {isTextMode && !isMinimized && (
          <div
            style={{
              position: "fixed",
              bottom: 40,
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
                width: Math.min(560, vp.w - 80),
                height: Math.min(300, Math.max(200, vp.h * 0.36)),
                display: "flex",
                flexDirection: "column",
                padding: 20,
                borderRadius: 18,
                pointerEvents: "auto",
                background: "rgba(2,5,8,0.86)",
                backdropFilter: "blur(20px)",
                WebkitBackdropFilter: "blur(20px)",
                border: `1px solid ${accent}55`,
                boxShadow: `0 0 30px ${accent}20, inset 0 1px 0 rgba(255,255,255,0.1)`,
                fontFamily: MONO,
              }}
            >
              <div className="jv-scroll" style={{ flex: 1, overflowY: "auto", fontSize: 13, color: "rgba(200,250,255,0.88)" }}>
                {messages.length === 0 && (
                  <p style={{ margin: 0, color: "rgba(142,245,255,0.45)" }}>
                    Chat link ready. Type anything, or ask me to switch engine, go offline, remember this…
                  </p>
                )}
                {messages.map((m) => (
                  <div key={m.id} style={{ margin: "0 0 12px", whiteSpace: "pre-wrap", wordBreak: "break-word", lineHeight: 1.5 }}>
                    <span style={{ color: m.from === "jarvis" ? CYAN : ORANGE, fontWeight: 700 }}>
                      {m.from === "jarvis" ? "Jarvis" : "You"}
                    </span>
                    <span style={{ color: "rgba(255,255,255,0.3)" }}>{"  ›  "}</span>
                    {m.text}
                  </div>
                ))}
                {(isProcessing || isSpeaking) && lastIsYou && (
                  <div style={{ color: CYAN, letterSpacing: "0.3em" }}>
                    {[0, 1, 2].map((i) => (
                      <span key={i} style={{ animation: `jv-dot 1.2s ${i * 0.2}s infinite` }}>●</span>
                    ))}
                  </div>
                )}
                <div ref={chatEndRef} />
              </div>
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 10,
                  marginTop: 12,
                  paddingTop: 12,
                  borderTop: `1px solid ${accent}55`,
                }}
              >
                <input
                  className="jv-input"
                  type="text"
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && sendMessage()}
                  placeholder="Type to Jarvis…"
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
                    color: accent,
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