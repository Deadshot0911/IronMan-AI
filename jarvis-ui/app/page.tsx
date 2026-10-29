"use client";
import { useState, useRef, useMemo } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Mic, MessageSquare, History, Cpu, Minimize2, Maximize2 } from "lucide-react";
import { Canvas, useFrame } from "@react-three/fiber";
import { Line } from "@react-three/drei";
import * as THREE from "three";

// --- DYNAMIC LINES COMPONENT ---
function DynamicLines() {
  const lineRef = useRef<THREE.Group>(null);
  const [lines, setLines] = useState<{ start: THREE.Vector3; end: THREE.Vector3; opacity: number }[]>([]);
  const timer = useRef(0);

  useFrame((_, delta) => {
    if (!lineRef.current) return;
    timer.current += delta;

    if (timer.current > 0.15) {
      timer.current = 0;
      setLines((prev) => {
        let newLines = [...prev];
        if (Math.random() > 0.4) {
          const start = new THREE.Vector3(
            (Math.random() - 0.5) * 3.5,
            (Math.random() - 0.5) * 3.5,
            (Math.random() - 0.5) * 3.5
          );
          const end = start.clone().add(new THREE.Vector3(
            (Math.random() - 0.5) * 1.5,
            (Math.random() - 0.5) * 1.5,
            (Math.random() - 0.5) * 1.5
          ));
          newLines.push({ start, end, opacity: 0 });
        }
        newLines = newLines.map(l => ({ ...l, opacity: Math.min(1, l.opacity + 0.1) }));
        if (newLines.length > 20) newLines.shift(); 
        return newLines;
      });
    }

    lineRef.current.rotation.x += delta * 0.05;
    lineRef.current.rotation.y += delta * 0.08;
    lineRef.current.rotation.z = Math.sin(Date.now() * 0.0004) * 0.1;
  });

  return (
    <group ref={lineRef}>
      {lines.map((line, i) => (
        <Line key={i} points={[line.start, line.end]} color="#00ffff" lineWidth={1} transparent opacity={line.opacity * 0.3} />
      ))}
    </group>
  );
}

// --- 3D HOLOGRAM COMPONENT ---
function Hologram({ state, isMinimized, hoveredButton }: { state: string; isMinimized: boolean; hoveredButton: string | null }) {
  const groupRef = useRef<THREE.Group>(null);
  const internalTimer = useRef(0);
  const materialRef = useRef<THREE.ShaderMaterial>(null);

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
      const mixedColor = rand < 0.6 ? colorCyan : rand < 0.9 ? colorWhite : colorBlue;
      
      cols[i * 3] = mixedColor.r;
      cols[i * 3 + 1] = mixedColor.g;
      cols[i * 3 + 2] = mixedColor.b;
    }
    return [pos, cols];
  }, []);

  const customMaterial = useMemo(() => {
    return new THREE.ShaderMaterial({
      uniforms: {
        uBulgeDir: { value: new THREE.Vector3(0, 0, 0) },
        uBulgeStrength: { value: 0 },
      },
      vertexShader: `
        uniform vec3 uBulgeDir;
        uniform float uBulgeStrength;
        
        varying vec3 vColor;

        void main() {
          vColor = color;
          
          vec3 pos = position;
          
          float dotProduct = dot(normalize(pos), normalize(uBulgeDir));
          float bulgeFactor = smoothstep(0.0, 1.0, dotProduct) * uBulgeStrength;
          
          pos += normalize(pos) * bulgeFactor * 0.8;
          
          vec4 mvPosition = modelViewMatrix * vec4(pos, 1.0);
          gl_PointSize = 15.0 * (1.0 / -mvPosition.z); 
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

  useFrame((_, delta) => {
    if (!groupRef.current || !materialRef.current) return;
    
    internalTimer.current += delta;

    groupRef.current.rotation.x += delta * 0.08;
    groupRef.current.rotation.y += delta * 0.12;
    groupRef.current.rotation.z = Math.sin(internalTimer.current * 0.3) * 0.1;

    let targetDir = new THREE.Vector3(0, 0, 0);
    let strength = 0;
    
    if (hoveredButton) {
      if (hoveredButton === "text") targetDir.set(0, 1, 0);
      if (hoveredButton === "voice") targetDir.set(1, 0, 0);
      if (hoveredButton === "memory") targetDir.set(0, -1, 0);
      if (hoveredButton === "engine") targetDir.set(-1, 0, 0);
      strength = 1.0;
    }

    const inverseRotation = new THREE.Quaternion().copy(groupRef.current.quaternion).invert();
    targetDir.applyQuaternion(inverseRotation);

    materialRef.current.uniforms.uBulgeDir.value.lerp(targetDir, 0.1);
    materialRef.current.uniforms.uBulgeStrength.value = THREE.MathUtils.lerp(
      materialRef.current.uniforms.uBulgeStrength.value, 
      strength, 
      0.1
    );

    let targetScale = 1;
    if (state === "speaking") targetScale = 1.1 + Math.sin(Date.now() * 0.01) * 0.05;
    else if (state === "listening") targetScale = 1.0 + Math.sin(Date.now() * 0.005) * 0.02;
    
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
          <primitive object={customMaterial} ref={materialRef} />
        </points>
      </group>
      {!isMinimized && <DynamicLines />}
    </group>
  );
}

// --- MAIN UI COMPONENT ---
export default function JarvisUI() {
  const [isListening, setIsListening] = useState(true);
  const [isProcessing, setIsProcessing] = useState(false);
  const [isTextMode, setIsTextMode] = useState(false);
  const [isMinimized, setIsMinimized] = useState(false);
  const [hoveredButton, setHoveredButton] = useState<string | null>(null);

  const hologramState = isProcessing ? "speaking" : isListening ? "listening" : "standby";

  const radius = 240;
  const buttons = [
    { id: "text", icon: <MessageSquare size={24} />, label: "Text Mode", onClick: () => setIsTextMode(!isTextMode), active: isTextMode, angle: -90 },
    { id: "voice", icon: <Mic size={24} />, label: "Voice Mode", onClick: () => setIsTextMode(false), active: !isTextMode, angle: 0 },
    { id: "memory", icon: <History size={24} />, label: "Memory", angle: 90 },
    { id: "engine", icon: <Cpu size={24} />, label: "Engine", angle: 180 },
  ];

  return (
    <div className="h-screen w-screen bg-black overflow-hidden relative flex items-center justify-center">
      
      <div className={`absolute w-[600px] h-[600px] rounded-full blur-[100px] pointer-events-none transition-colors duration-1000 ${
        isProcessing ? "bg-orange-500/10" : "bg-cyan-500/10"
      }`} />

      <AnimatePresence>
        {!isMinimized && (
          <motion.div
            initial={{ opacity: 0, scale: 0.9, filter: "blur(10px)" }}
            animate={{ opacity: 1, scale: 1, filter: "blur(0px)" }}
            exit={{ opacity: 0, scale: 0.5, filter: "blur(10px)" }}
            transition={{ duration: 0.6, ease: "easeInOut" }}
            className="relative w-[700px] h-[700px] flex items-center justify-center"
          >
            {/* 🛠️ FIX: Using absolute inset-0 to perfectly center the 3D Canvas */}
            <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
              <div className="w-full h-full pointer-events-auto">
                <Canvas camera={{ position: [0, 0, 6], fov: 50 }}>
                  <Hologram state={hologramState} isMinimized={false} hoveredButton={hoveredButton} />
                </Canvas>
              </div>
            </div>

            {/* 🛠️ FIX: Absolute centering for the text */}
            <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none z-20">
              <h1 className={`text-xl font-bold tracking-[0.3em] font-mono ${isProcessing ? "text-orange-400" : "text-cyan-400"} drop-shadow-[0_0_15px_rgba(0,255,255,0.8)] transition-colors duration-500`}>
                {isProcessing ? "PROCESSING" : isListening ? "LISTENING" : "STANDBY"}
              </h1>
            </div>

            {/* 🛠️ FIX: Absolute centering for buttons with exact radius math */}
            <div className="absolute inset-0 pointer-events-none flex items-center justify-center z-30">
              {buttons.map((btn) => {
                const rad = (btn.angle * Math.PI) / 180;
                const x = Math.cos(rad) * radius;
                const y = Math.sin(rad) * radius;
                
                return (
                  <div 
                    key={btn.id} 
                    className="absolute pointer-events-auto"
                    style={{ transform: `translate(${x}px, ${y}px)` }}
                    onMouseEnter={() => setHoveredButton(btn.id)}
                    onMouseLeave={() => setHoveredButton(null)}
                  >
                    <IconButton {...btn} />
                  </div>
                );
              })}
            </div>

            <button
              onClick={() => setIsMinimized(true)}
              className="absolute top-6 right-6 text-cyan-500/70 hover:text-white transition-colors z-[100] p-4 bg-white/5 rounded-full backdrop-blur-md border border-white/10"
            >
              <Minimize2 size={24} />
            </button>
          </motion.div>
        )}
      </AnimatePresence>

      <AnimatePresence>
        {isMinimized && (
          <motion.div
            initial={{ opacity: 0, scale: 0, x: 50, y: 50 }}
            animate={{ opacity: 1, scale: 1, x: 0, y: 0 }}
            exit={{ opacity: 0, scale: 0 }}
            whileHover={{ scale: 1.1 }}
            className="fixed bottom-10 right-10 w-32 h-32 cursor-pointer z-50 group flex items-center justify-center"
            onClick={() => setIsMinimized(false)}
          >
            <div className="absolute inset-0">
              <Canvas camera={{ position: [0, 0, 5], fov: 50 }}>
                <Hologram state={hologramState} isMinimized={true} hoveredButton={null} />
              </Canvas>
            </div>
            <div className="absolute inset-0 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity duration-300 pointer-events-none">
              <Maximize2 size={24} className="text-cyan-300 drop-shadow-[0_0_10px_rgba(0,255,255,1)]" />
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {isTextMode && !isMinimized && (
        <motion.div
          initial={{ opacity: 0, y: 30 }}
          animate={{ opacity: 1, y: 0 }}
          className="fixed bottom-10 w-[500px] h-56 bg-black/60 backdrop-blur-xl rounded-2xl border border-cyan-500/30 shadow-[0_0_30px_rgba(0,255,255,0.1)] p-5 flex flex-col z-[100]"
        >
          <div className="flex-1 overflow-y-auto text-cyan-100/80 text-sm font-mono">
            <p className="mb-4"><span className="text-cyan-400 font-bold">Jarvis:</span> Good evening, Sir. How may I assist you?</p>
          </div>
          <input
            type="text"
            placeholder="Type command, Sir..."
            className="w-full bg-transparent border-t border-cyan-500/30 mt-4 pt-4 text-cyan-100 outline-none font-mono"
          />
        </motion.div>
      )}
    </div>
  );
}

function IconButton({ icon, label, onClick, active = false }: { icon: React.ReactNode, label: string, onClick?: () => void, active?: boolean }) {
  return (
    <div className="relative group flex flex-col items-center">
      <button
        onClick={onClick}
        className={`relative w-16 h-16 rounded-full flex items-center justify-center backdrop-blur-xl transition-all duration-300 ${
          active 
            ? "bg-cyan-500/20 border border-cyan-400 text-cyan-300 shadow-[0_0_20px_rgba(0,255,255,0.4)]" 
            : "bg-white/5 border border-white/10 text-gray-400 hover:bg-white/10 hover:border-cyan-500/50 hover:text-cyan-200 hover:shadow-[0_0_15px_rgba(0,255,255,0.2)]"
        }`}
      >
        <div className="absolute inset-0 rounded-full bg-gradient-to-b from-white/10 to-transparent pointer-events-none" />
        <div className="relative z-10">{icon}</div>
      </button>
      
      <div className="absolute top-full mt-3 px-3 py-1 bg-black/90 text-cyan-300 text-[10px] uppercase tracking-wider rounded opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none whitespace-nowrap border border-cyan-500/30 shadow-[0_0_10px_rgba(0,255,255,0.2)]">
        {label}
      </div>
    </div>
  );
}