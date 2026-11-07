"use client";

import { useState, useRef, useMemo, useEffect } from "react";
import type { ReactNode, CSSProperties } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Mic,
  MicOff,
  MessageSquare,
  History,
  Cpu,
  Minimize2,
  Maximize2,
  SendHorizontal,
  X,
  PanelLeftClose,
  PanelLeftOpen,
  Plus,
  Archive,
  RotateCcw,
  Shield,
  Trash2,
} from "lucide-react";
import { Canvas, useFrame } from "@react-three/fiber";
import * as THREE from "three";
import "./jarvis-glass.css";

const CYAN = "#22e5ff";
const ORANGE = "#ff9a3c";
const VIOLET = "#8b5cff";
const RED = "#ff5470";
const MONO = "ui-monospace, SFMono-Regular, Menlo, monospace";

type Msg = { id: number | string; from: "jarvis" | "you"; text: string };
type AuthUser = { id: number; username: string; role: "admin" | "user"; active: boolean; gender?: string | null };
type UserEvent = { username: string; action: "disabled" | "enabled" | "deleted"; created_at: string };
type AuthState = {
  ready: boolean;
  required: boolean;
  setup: boolean;
  mode: string;
  admin_name: string;
  login_username?: string | null;
  user: AuthUser | null;
  management: {
    mode: string;
    step?: string;
    username?: string;
    spelling?: string;
    operation?: string;
    user_id?: number;
  } | null;
  users: AuthUser[];
  user_events: UserEvent[];
  error: string;
  pending_action?: {
    stage: string;
    label: string;
    source?: string;
    draft?: {
      kind: string;
      to?: string;
      display_to?: string;
      subject?: string;
      body?: string;
      phone?: string;
      message?: string;
    };
    warning?: string;
    command?: string;
    screen_plan?: {
      summary?: string;
      answer?: string;
      instruction?: string;
      screenshot?: string;
      actions?: Array<{
        type?: string;
        description?: string;
        x?: number;
        y?: number;
        text?: string;
        key?: string;
        keys?: string[];
      }>;
    };
  } | null;
  history?: Msg[] | null;
  active_conversation_id?: number | string | null;
  private_mode?: boolean;
};
type Conversation = {
  id: number | string;
  title: string;
  started_at: string;
  active: boolean;
  private?: boolean;
  archived?: boolean;
};
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

function AuthScreen({
  auth,
  send,
  close,
}: {
  auth: AuthState;
  send: (data: object) => void;
  close: () => void;
}) {
  const [username, setUsername] = useState(
    auth.setup || auth.mode === "admin_takeover" ? auth.admin_name : "",
  );
  const [pin, setPin] = useState("");
  const [confirmPin, setConfirmPin] = useState("");
  const isSetup = auth.setup;
  const isTakeover = auth.mode === "admin_takeover";
  const loginUsername = auth.login_username || (isTakeover ? auth.admin_name : "");
  const pinStep = isSetup || isTakeover || Boolean(loginUsername);

  const submit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!isSetup && !isTakeover && !pinStep) {
      send({ do: "username", username: username.trim() });
      return;
    }
    if (isSetup && pin !== confirmPin) return;
    send({
      do: isSetup ? "bootstrap" : "login",
      pin,
    });
    setPin("");
    setConfirmPin("");
  };

  return (
    <main
      style={{
        position: "fixed",
        inset: 0,
        display: "grid",
        placeItems: "center",
        padding: 24,
        color: "#d4fbff",
        background: "radial-gradient(ellipse at 50% 45%, #0c202a 0%, #06111b 48%, #02060b 100%)",
        fontFamily: MONO,
      }}
    >
      <button
        type="button"
        onClick={() => isTakeover ? send({ do: "cancel_admin_takeover" }) : close()}
        aria-label={isTakeover ? "Return to current user session" : "Close Jarvis"}
        title={isTakeover ? "Return to current user session" : "Close Jarvis"}
        style={{
          position: "fixed",
          top: 24,
          right: 24,
          zIndex: 400,
          width: 44,
          height: 44,
          borderRadius: "50%",
          display: "grid",
          placeItems: "center",
          color: "#ff9aaa",
          border: "1px solid rgba(255,154,170,0.28)",
          background: "rgba(12,21,29,0.78)",
          cursor: "pointer",
        }}
      >
        <X size={20} />
      </button>
      <form
        onSubmit={submit}
        style={{
          width: "min(400px, 100%)",
          padding: 28,
          borderRadius: 22,
          background: "rgba(9,24,34,0.82)",
          border: "1px solid rgba(34,229,255,0.34)",
          boxShadow: "0 0 42px rgba(34,229,255,0.14), inset 0 1px rgba(255,255,255,0.1)",
          backdropFilter: "blur(24px)",
        }}
      >
        <div style={{ color: CYAN, fontSize: 10, letterSpacing: "0.3em" }}>J.A.R.V.I.S. · SECURE SESSION</div>
        <h1 style={{ margin: "14px 0 8px", fontSize: 22, letterSpacing: "0.12em" }}>
          {isSetup ? "INITIAL ADMIN SETUP" : isTakeover ? "ADMIN CONTROL" : "WHO'S THERE?"}
        </h1>
        <p style={{ margin: "0 0 22px", color: "rgba(190,239,255,0.66)", fontSize: 12, lineHeight: 1.6 }}>
          {isSetup
            ? `Create the ${auth.admin_name} administrator account. Choose a 4–8 digit PIN.`
            : isTakeover
            ? "The current user session is paused. Enter the administrator PIN to switch, or close this window to resume it."
            : pinStep
            ? "Enter your PIN in this private sign-in window."
            : "Say your username, or type it below. Jarvis will ask for your PIN here."}
        </p>
        {!isSetup && !isTakeover && !pinStep && (
          <label style={authLabel}>
            USERNAME
            <input
              autoComplete="username"
              autoFocus
              placeholder="Say it or type your username"
              maxLength={60}
              required
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              style={authInput}
            />
          </label>
        )}
        {!isSetup && !isTakeover && pinStep && (
          <div style={{ ...authInput, marginBottom: 14, display: "flex", justifyContent: "space-between" }}>
            <span>{loginUsername}</span>
            <button type="button" onClick={() => { setPin(""); send({ do: "username_reset" }); }} style={authBackButton}>
              CHANGE
            </button>
          </div>
        )}
        {(isSetup || isTakeover) && (
          <div style={{ ...authInput, marginBottom: 14, color: CYAN }}>
            {auth.admin_name} · ADMIN
          </div>
        )}
        {(pinStep || isSetup || isTakeover) && (
          <>
            <label style={authLabel}>
              {isSetup ? "CREATE ADMIN PIN" : isTakeover || loginUsername.toLowerCase() === auth.admin_name.toLowerCase() ? "ADMIN PIN" : "PIN"}
              <input
                autoComplete={isSetup ? "new-password" : "current-password"}
                autoFocus
                inputMode="numeric"
                maxLength={8}
                minLength={4}
                pattern="[0-9]{4,8}"
                required
                type="password"
                value={pin}
                onChange={(event) => setPin(event.target.value.replace(/\D/g, "").slice(0, 8))}
                style={authInput}
              />
            </label>
            {isSetup && (
              <label style={authLabel}>
                CONFIRM ADMIN PIN
                <input
                  autoComplete="new-password"
                  inputMode="numeric"
                  maxLength={8}
                  minLength={4}
                  pattern="[0-9]{4,8}"
                  required
                  type="password"
                  value={confirmPin}
                  onChange={(event) => setConfirmPin(event.target.value.replace(/\D/g, "").slice(0, 8))}
                  style={authInput}
                />
              </label>
            )}
            {isSetup && confirmPin && pin !== confirmPin && (
              <p role="alert" style={authErrorStyle}>The PINs do not match.</p>
            )}
          </>
        )}
        {auth.error && <p role="alert" style={authErrorStyle}>{auth.error}</p>}
        <button type="submit" style={authPrimaryButton}>
          {isSetup ? "CREATE ADMIN ACCOUNT" : isTakeover ? "VERIFY ADMIN PIN" : pinStep ? "UNLOCK SESSION" : "CONFIRM USERNAME"}
        </button>
        {isTakeover && (
          <button
            type="button"
            onClick={() => send({ do: "cancel_admin_takeover" })}
            style={{ ...authSecondaryButton, width: "100%", marginTop: 10 }}
          >
            RETURN TO CURRENT SESSION
          </button>
        )}
      </form>
    </main>
  );
}

function GenderSetup({
  auth,
  send,
  close,
}: {
  auth: AuthState;
  send: (data: object) => void;
  close: () => void;
}) {
  return (
    <main
      style={{
        position: "fixed",
        inset: 0,
        display: "grid",
        placeItems: "center",
        padding: 24,
        color: "#d4fbff",
        background: "radial-gradient(ellipse at 50% 45%, #0c202a 0%, #06111b 48%, #02060b 100%)",
        fontFamily: MONO,
      }}
    >
      <button
        type="button"
        onClick={close}
        aria-label="Close Jarvis"
        title="Close Jarvis"
        style={{
          position: "fixed",
          top: 24,
          right: 24,
          zIndex: 400,
          width: 44,
          height: 44,
          borderRadius: "50%",
          display: "grid",
          placeItems: "center",
          color: "#ff9aaa",
          border: "1px solid rgba(255,154,170,0.28)",
          background: "rgba(12,21,29,0.78)",
          cursor: "pointer",
        }}
      >
        <X size={20} />
      </button>
      <section
        role="dialog"
        aria-modal="true"
        aria-labelledby="gender-setup-title"
        style={{
          width: "min(400px, 100%)",
          padding: 28,
          borderRadius: 22,
          background: "rgba(9,24,34,0.82)",
          border: "1px solid rgba(34,229,255,0.34)",
          boxShadow: "0 0 42px rgba(34,229,255,0.14)",
          backdropFilter: "blur(24px)",
        }}
      >
        <div style={{ color: CYAN, fontSize: 10, letterSpacing: "0.3em" }}>J.A.R.V.I.S. · USER PROFILE</div>
        <h1 id="gender-setup-title" style={{ margin: "14px 0 8px", fontSize: 20 }}>
          HOW SHOULD I GREET YOU?
        </h1>
        <p style={{ margin: "0 0 20px", color: "rgba(190,239,255,0.66)", fontSize: 12, lineHeight: 1.6 }}>
          This is saved to {auth.user?.username}&apos;s profile and only affects greetings.
        </p>
        <div style={{ display: "grid", gap: 9 }}>
          {[
            ["male", "Male · Sir"],
            ["female", "Female · Ma’am"],
            ["non_binary", "Non-binary · use my name"],
            ["prefer_not_to_say", "Prefer not to say · use my name"],
          ].map(([gender, label]) => (
            <button
              key={gender}
              onClick={() => send({ do: "set_gender", gender })}
              style={authSecondaryButton}
            >
              {label}
            </button>
          ))}
        </div>
        {auth.error && <p role="alert" style={authErrorStyle}>{auth.error}</p>}
      </section>
    </main>
  );
}

const authLabel: CSSProperties = {
  display: "grid",
  gap: 8,
  marginBottom: 14,
  color: "rgba(190,239,255,0.66)",
  fontSize: 10,
  letterSpacing: "0.18em",
};
const authInput: CSSProperties = {
  width: "100%",
  boxSizing: "border-box",
  padding: "12px 13px",
  color: "#e5fcff",
  background: "rgba(0,0,0,0.28)",
  border: "1px solid rgba(34,229,255,0.24)",
  borderRadius: 10,
  outline: "none",
  font: `14px ${MONO}`,
};
const authErrorStyle: CSSProperties = {
  margin: "2px 0 14px",
  color: "#ff9aaa",
  fontSize: 12,
  lineHeight: 1.5,
};
const authPrimaryButton: CSSProperties = {
  width: "100%",
  marginTop: 6,
  padding: "13px 16px",
  border: "1px solid rgba(34,229,255,0.44)",
  borderRadius: 10,
  color: "#dffcff",
  background: "rgba(34,229,255,0.12)",
  font: `11px ${MONO}`,
  letterSpacing: "0.16em",
  cursor: "pointer",
};
const authBackButton: CSSProperties = {
  border: "none",
  padding: 0,
  color: CYAN,
  background: "transparent",
  font: `9px ${MONO}`,
  letterSpacing: "0.12em",
  cursor: "pointer",
};
const authSecondaryButton: CSSProperties = {
  padding: "10px 12px",
  border: "1px solid rgba(34,229,255,0.2)",
  borderRadius: 9,
  color: "#c9f8ff",
  background: "rgba(255,255,255,0.04)",
  font: `10px ${MONO}`,
  letterSpacing: "0.12em",
  cursor: "pointer",
};
const authDangerButton: CSSProperties = {
  ...authSecondaryButton,
  flex: 1,
  borderColor: "rgba(255,84,112,0.5)",
  color: "#ff9aaa",
};
const discussionIconButton: CSSProperties = {
  width: 32,
  height: 32,
  flex: "0 0 auto",
  display: "grid",
  placeItems: "center",
  border: "1px solid rgba(34,229,255,0.14)",
  borderRadius: 8,
  color: "#bfefff",
  background: "rgba(255,255,255,0.035)",
  cursor: "pointer",
};

function UserManagementDialog({
  auth,
  send,
}: {
  auth: AuthState;
  send: (data: object) => void;
}) {
  const [username, setUsername] = useState(
    auth.management?.step === "username" ? auth.management.username || "" : "",
  );
  const [pin, setPin] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [adminPin, setAdminPin] = useState("");
  const [sessionPin, setSessionPin] = useState("");

  if (!auth.management) return null;
  const adding = auth.management.mode === "add_user";
  const managing = auth.management.mode === "users";
  const userAction = auth.management.mode === "user_action";
  const endingSession = auth.management.mode === "end_session";
  const usernameStep = adding && auth.management.step === "username";
  const spellingStep = adding && auth.management.step === "spelling";
  const genderStep = adding && auth.management.step === "gender";

  const addUser = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (usernameStep) {
      send({ do: "set_add_username", username: username.trim() });
      setUsername("");
      return;
    }
    if (spellingStep) {
      send({ do: "set_add_spelling", spelling: username.trim() });
      return;
    }
    if (genderStep) return;
    if (pin !== confirmation) {
      setConfirmation("");
      return;
    }
    send({ do: "add_user", username: username.trim(), pin });
    setPin("");
    setConfirmation("");
  };
  const confirmUserAction = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    send({ do: "manage_user", admin_pin: adminPin });
    setAdminPin("");
  };
  const confirmEndSession = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    send({ do: "confirm_end_session", user_pin: sessionPin });
    setSessionPin("");
  };
  const prepareAction = (user: AuthUser, operation: "disable" | "enable" | "delete") =>
    send({ do: "prepare_user_action", user_id: user.id, operation });

  return (
    <div
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) send({ do: "close_management" });
      }}
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 300,
        display: "grid",
        placeItems: "center",
        padding: 20,
        background: "rgba(0,4,8,0.74)",
        backdropFilter: "blur(12px)",
        fontFamily: MONO,
      }}
    >
      <section
        role="dialog"
        aria-modal="true"
        aria-labelledby="user-management-title"
        style={{
          width: "min(420px, 100%)",
          padding: 24,
          borderRadius: 18,
          color: "#d4fbff",
          background: "rgba(8,23,33,0.96)",
          border: "1px solid rgba(34,229,255,0.34)",
          boxShadow: "0 0 42px rgba(34,229,255,0.16)",
        }}
      >
        <h2 id="user-management-title" style={{ margin: "0 0 8px", fontSize: 18 }}>
          {endingSession
            ? "END SESSION · PIN REQUIRED"
            : auth.management.mode === "permanently_delete_history"
            ? "PERMANENTLY DELETE HISTORY?"
            : adding
            ? "ADD A USER"
            : userAction
            ? auth.management.step === "admin_pin" ? "ADMIN PIN REQUIRED" : "CONFIRM USER ACTION"
            : "MANAGE USERS"}
        </h2>
        <p style={{ margin: "0 0 18px", color: "rgba(190,239,255,0.65)", fontSize: 12, lineHeight: 1.6 }}>
          {endingSession
            ? "Enter your account PIN to end this session and return to sign-in. Your account and chat history will not be deleted."
            : auth.management.mode === "permanently_delete_history"
            ? "This permanently deletes all your cloud conversations, private local discussions, and saved Jarvis memory. Your account remains."
            : adding
            ? usernameStep
              ? "Say the new user's name, or type it below. PINs are entered only here."
              : spellingStep
              ? `Say ${auth.management.username}'s spelling one letter at a time, then say “done.” Say “clear” to restart, or type the spelling below.`
              : genderStep
              ? `Say ${auth.management.username}'s gender, or choose an option below.`
              : "Choose and confirm a 4–8 digit PIN. Their conversation history will be separate."
            : userAction
            ? auth.management.step === "admin_pin"
              ? `Enter your administrator PIN to ${auth.management.operation} ${auth.management.username}.`
              : `Say “confirm” or press Confirm to ${auth.management.operation} ${auth.management.username}. This action requires your administrator PIN.`
            : "Review active, disabled, and recently deleted accounts. Delete permanently removes that user's account and history."}
        </p>
        {endingSession ? (
          <form onSubmit={confirmEndSession}>
            <label style={authLabel}>
              YOUR ACCOUNT PIN
              <input
                autoFocus
                autoComplete="current-password"
                inputMode="numeric"
                maxLength={8}
                minLength={4}
                pattern="[0-9]{4,8}"
                required
                type="password"
                value={sessionPin}
                onChange={(event) => setSessionPin(event.target.value.replace(/\D/g, "").slice(0, 8))}
                style={authInput}
              />
            </label>
            {auth.error && <p role="alert" style={authErrorStyle}>{auth.error}</p>}
            <div style={{ display: "flex", gap: 10 }}>
              <button type="button" onClick={() => send({ do: "close_management" })} style={authSecondaryButton}>
                CANCEL
              </button>
              <button type="submit" style={authDangerButton}>END SESSION</button>
            </div>
          </form>
        ) : auth.management.mode === "permanently_delete_history" ? (
          <div style={{ display: "flex", gap: 10 }}>
            <button onClick={() => send({ do: "close_management" })} style={authSecondaryButton}>
              CANCEL
            </button>
            <button
              onClick={() => send({ do: "permanently_delete_history" })}
              style={authDangerButton}
            >
              DELETE EVERYTHING
            </button>
          </div>
        ) : adding ? (
          <form onSubmit={addUser}>
            {usernameStep || spellingStep ? (
              <label style={authLabel}>
                {usernameStep ? "USERNAME" : "SPELL THE USERNAME"}
                <input
                  autoFocus
                  autoComplete="off"
                  maxLength={60}
                  required
                  value={username}
                  onChange={(event) => setUsername(event.target.value)}
                  placeholder={spellingStep ? "Type the corrected spelling" : "Enter the user's name"}
                  style={authInput}
                />
              </label>
            ) : (
              <div style={{ ...authInput, marginBottom: 14 }}>{auth.management.username}</div>
            )}
            {spellingStep && auth.management.spelling && (
              <p role="status" style={{ color: CYAN, fontSize: 12, letterSpacing: 2 }}>
                HEARD SO FAR: {auth.management.spelling.toUpperCase().split("").join(" · ")}
              </p>
            )}
            {genderStep && (
              <div style={{ display: "grid", gap: 8, marginBottom: 14 }}>
                {[
                  ["male", "MALE"],
                  ["female", "FEMALE"],
                  ["non_binary", "NON-BINARY"],
                  ["prefer_not_to_say", "PREFER NOT TO SAY"],
                ].map(([gender, label]) => (
                  <button
                    key={gender}
                    type="button"
                    onClick={() => send({ do: "set_add_gender", gender })}
                    style={authSecondaryButton}
                  >
                    {label}
                  </button>
                ))}
              </div>
            )}
            {adding && auth.management.step === "pin" && (
              <>
                <label style={authLabel}>
                  NEW USER PIN
                  <input
                    autoComplete="new-password"
                    inputMode="numeric"
                    maxLength={8}
                    minLength={4}
                    pattern="[0-9]{4,8}"
                    required
                    type="password"
                    value={pin}
                    onChange={(event) => setPin(event.target.value.replace(/\D/g, "").slice(0, 8))}
                    style={authInput}
                  />
                </label>
                <label style={authLabel}>
                  CONFIRM PIN
                  <input
                    autoComplete="new-password"
                    inputMode="numeric"
                    maxLength={8}
                    minLength={4}
                    pattern="[0-9]{4,8}"
                    required
                    type="password"
                    value={confirmation}
                    onChange={(event) => setConfirmation(event.target.value.replace(/\D/g, "").slice(0, 8))}
                    style={authInput}
                  />
                </label>
                {confirmation && pin !== confirmation && (
                  <p role="alert" style={authErrorStyle}>The PINs do not match.</p>
                )}
              </>
            )}
            {auth.error && <p role="alert" style={authErrorStyle}>{auth.error}</p>}
            {!genderStep && (
              <button type="submit" style={authPrimaryButton}>
                {usernameStep ? "CONTINUE TO SPELLING" : spellingStep ? "CONFIRM SPELLING" : "SAVE USER"}
              </button>
            )}
          </form>
        ) : userAction && auth.management.step === "confirm" ? (
          <div style={{ display: "flex", gap: 10 }}>
            <button onClick={() => send({ do: "close_management" })} style={authSecondaryButton}>CANCEL</button>
            <button onClick={() => send({ do: "confirm_user_action" })} style={authDangerButton}>
              CONFIRM
            </button>
          </div>
        ) : userAction && auth.management.step === "admin_pin" ? (
          <form onSubmit={confirmUserAction}>
            <label style={authLabel}>
              ADMINISTRATOR PIN
              <input
                autoFocus
                autoComplete="current-password"
                inputMode="numeric"
                maxLength={8}
                minLength={4}
                pattern="[0-9]{4,8}"
                required
                type="password"
                value={adminPin}
                onChange={(event) => setAdminPin(event.target.value.replace(/\D/g, "").slice(0, 8))}
                style={authInput}
              />
            </label>
            {auth.error && <p role="alert" style={authErrorStyle}>{auth.error}</p>}
            <button type="submit" style={authDangerButton}>AUTHORIZE ACTION</button>
          </form>
        ) : managing || userAction ? (
          <div style={{ display: "grid", gap: 8, maxHeight: "42vh", overflowY: "auto" }}>
            {auth.users.filter((user) => user.role === "user").map((user) => (
              <div key={user.id} style={{ ...authInput, display: "grid", gap: 8 }}>
                <span>{user.username} · {user.active ? "ACTIVE" : "DISABLED"}</span>
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                  {user.active ? (
                    <>
                      <button type="button" onClick={() => prepareAction(user, "disable")} style={authSecondaryButton}>DISABLE</button>
                      <button type="button" onClick={() => prepareAction(user, "delete")} style={authDangerButton}>DELETE PERMANENTLY</button>
                    </>
                  ) : (
                    <>
                      <button type="button" onClick={() => prepareAction(user, "enable")} style={authPrimaryButton}>ENABLE</button>
                      <button type="button" onClick={() => prepareAction(user, "delete")} style={authDangerButton}>DELETE PERMANENTLY</button>
                    </>
                  )}
                </div>
              </div>
            ))}
            {auth.users.every((user) => user.role !== "user") && (
              <p style={{ color: "rgba(190,239,255,0.58)", fontSize: 12 }}>No regular accounts have been added.</p>
            )}
            {auth.user_events.length > 0 && (
              <div style={{ marginTop: 8, borderTop: "1px solid rgba(34,229,255,0.14)", paddingTop: 8 }}>
                <strong style={{ fontSize: 11 }}>RECENT ACCOUNT CHANGES</strong>
                {auth.user_events.map((event, index) => (
                  <p key={`${event.username}-${event.created_at}-${index}`} style={{ margin: "6px 0", color: "rgba(190,239,255,0.62)", fontSize: 11 }}>
                    {event.username} · {event.action.toUpperCase()} · {new Date(event.created_at).toLocaleString()}
                  </p>
                ))}
              </div>
            )}
            {auth.error && <p role="status" style={{ color: CYAN, fontSize: 12 }}>{auth.error}</p>}
          </div>
        ) : null}
        {!adding && auth.error && (
          <p role="status" style={{ color: CYAN, fontSize: 12 }}>{auth.error}</p>
        )}
        <button
          onClick={() => send({ do: "close_management" })}
          style={{ ...authSecondaryButton, marginTop: 14 }}
        >
          CLOSE
        </button>
      </section>
    </div>
  );
}

function PendingActionDialog({
  auth,
  send,
}: {
  auth: AuthState;
  send: (data: object) => void;
}) {
  const [pin, setPin] = useState("");
  const pending = auth.pending_action;
  if (!pending) return null;

  const draft = pending.draft;
  const isDraft = pending.stage === "confirm_send";
  const isDanger = pending.stage === "danger_confirm";
  const isScreen = pending.stage === "confirm_screen";
  const kind = draft?.kind === "whatsapp" ? "WHATSAPP MESSAGE" : "EMAIL";
  const title = pending.stage === "admin_pin"
    ? "ADMIN AUTHORIZATION REQUIRED"
    : isDanger
    ? "CONFIRM DESTRUCTIVE ACTION"
    : isScreen
    ? "CONFIRM SCREEN ACTION"
    : `APPROVE ${kind}`;

  const authorize = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    send({ do: "authorize_action", admin_pin: pin });
    setPin("");
  };

  return (
    <div
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) send({ do: "cancel_pending_action" });
      }}
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 320,
        display: "grid",
        placeItems: "center",
        padding: 20,
        background: "rgba(0,4,8,0.78)",
        backdropFilter: "blur(12px)",
        fontFamily: MONO,
      }}
    >
      <section
        role="dialog"
        aria-modal="true"
        aria-labelledby="pending-action-title"
        style={{
          width: "min(460px, 100%)",
          padding: 24,
          borderRadius: 18,
          color: "#d4fbff",
          background: "rgba(8,23,33,0.97)",
          border: "1px solid rgba(34,229,255,0.34)",
          boxShadow: "0 0 42px rgba(34,229,255,0.16)",
        }}
      >
        <h2 id="pending-action-title" style={{ margin: "0 0 8px", fontSize: 18 }}>
          {title}
        </h2>
        <p style={{ margin: "0 0 16px", color: "rgba(190,239,255,0.65)", fontSize: 12, lineHeight: 1.6 }}>
          {pending.stage === "admin_pin"
            ? `A regular user asked Jarvis to ${pending.label}. Enter the administrator PIN to authorize this one action.`
            : isDanger
            ? pending.warning || "This action can change or damage the machine."
            : isScreen
            ? "Review the planned clicks and typing. Nothing happens on your screen until you confirm."
            : `Review the draft, then approve it. Nothing has been sent yet.`}
        </p>

        {pending.stage === "admin_pin" ? (
          <form onSubmit={authorize}>
            <label style={authLabel}>
              ADMINISTRATOR PIN
              <input
                type="password"
                inputMode="numeric"
                autoFocus
                value={pin}
                onChange={(event) => setPin(event.target.value.replace(/\D/g, "").slice(0, 8))}
                style={authInput}
              />
            </label>
            {auth.error && <p role="alert" style={authErrorStyle}>{auth.error}</p>}
            <button type="submit" style={authPrimaryButton}>AUTHORIZE ACTION</button>
            <button
              type="button"
              onClick={() => send({ do: "cancel_pending_action" })}
              style={{ ...authSecondaryButton, width: "100%", marginTop: 10 }}
            >
              CANCEL
            </button>
          </form>
        ) : isDanger ? (
          <div style={{ display: "grid", gap: 12 }}>
            {pending.command && (
              <pre style={{ margin: 0, padding: 12, borderRadius: 10, background: "rgba(0,0,0,0.3)", border: "1px solid rgba(255,84,112,0.3)", color: "#ffd7de", whiteSpace: "pre-wrap", wordBreak: "break-word", font: `12px ${MONO}` }}>
                {pending.command}
              </pre>
            )}
            {auth.error && <p role="alert" style={authErrorStyle}>{auth.error}</p>}
            <button type="button" onClick={() => send({ do: "confirm_pending_action" })} style={authDangerButton}>
              CONFIRM DANGEROUS
            </button>
            <button type="button" onClick={() => send({ do: "cancel_pending_action" })} style={authSecondaryButton}>
              CANCEL
            </button>
          </div>
        ) : isScreen ? (
          <div style={{ display: "grid", gap: 12 }}>
            <div style={{ display: "grid", gap: 8, padding: 12, borderRadius: 10, background: "rgba(0,0,0,0.26)", border: "1px solid rgba(34,229,255,0.18)" }}>
              {pending.screen_plan?.summary && (
                <div style={{ color: "#e5fcff", fontSize: 13, lineHeight: 1.5 }}>
                  {pending.screen_plan.summary}
                </div>
              )}
              {pending.screen_plan?.instruction && (
                <div style={{ color: "rgba(190,239,255,0.55)", fontSize: 10, letterSpacing: "0.14em" }}>
                  INSTRUCTION
                  <div style={{ color: "#d9fbff", fontSize: 12, letterSpacing: 0, marginTop: 3, lineHeight: 1.5 }}>
                    {pending.screen_plan.instruction}
                  </div>
                </div>
              )}
              {(pending.screen_plan?.actions?.length || 0) > 0 ? (
                <ol style={{ margin: 0, paddingLeft: 18, color: "#d9fbff", fontSize: 12, lineHeight: 1.7 }}>
                  {pending.screen_plan?.actions?.map((action, index) => (
                    <li key={`${action.type || "step"}-${index}`}>
                      {action.description || action.type || "screen action"}
                    </li>
                  ))}
                </ol>
              ) : (
                <div style={{ color: "rgba(190,239,255,0.65)", fontSize: 12 }}>
                  No steps were planned.
                </div>
              )}
            </div>
            {auth.error && <p role="alert" style={authErrorStyle}>{auth.error}</p>}
            <button type="button" onClick={() => send({ do: "confirm_pending_action" })} style={authPrimaryButton}>
              EXECUTE ON SCREEN
            </button>
            <button type="button" onClick={() => send({ do: "cancel_pending_action" })} style={authSecondaryButton}>
              CANCEL
            </button>
          </div>
        ) : isDraft ? (
          <div style={{ display: "grid", gap: 12 }}>
            <div style={{ display: "grid", gap: 8, padding: 12, borderRadius: 10, background: "rgba(0,0,0,0.26)", border: "1px solid rgba(34,229,255,0.18)" }}>
              <div style={{ color: "rgba(190,239,255,0.55)", fontSize: 10, letterSpacing: "0.14em" }}>
                TO
                <div style={{ color: "#e5fcff", fontSize: 13, letterSpacing: 0, marginTop: 3 }}>
                  {draft?.to} {draft?.phone ? `· ${draft.phone}` : ""}
                </div>
              </div>
              {draft?.kind === "email" && (
                <div style={{ color: "rgba(190,239,255,0.55)", fontSize: 10, letterSpacing: "0.14em" }}>
                  SUBJECT
                  <div style={{ color: "#e5fcff", fontSize: 13, letterSpacing: 0, marginTop: 3 }}>
                    {draft.subject}
                  </div>
                </div>
              )}
              <pre style={{ margin: 0, color: "#d9fbff", whiteSpace: "pre-wrap", wordBreak: "break-word", font: `12px/1.6 ${MONO}` }}>
                {draft?.kind === "email" ? draft.body : draft?.message}
              </pre>
            </div>
            {auth.error && <p role="alert" style={authErrorStyle}>{auth.error}</p>}
            <button type="button" onClick={() => send({ do: "confirm_pending_action" })} style={authPrimaryButton}>
              {draft?.kind === "whatsapp" ? "OPEN WHATSAPP WITH MESSAGE" : "SEND EMAIL"}
            </button>
            <button type="button" onClick={() => send({ do: "cancel_pending_action" })} style={authSecondaryButton}>
              CANCEL
            </button>
          </div>
        ) : null}
      </section>
    </div>
  );
}

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
  const [auth, setAuth] = useState<AuthState>({
    ready: false,
    required: true,
    setup: false,
    mode: "login",
    admin_name: "Sunrit",
    login_username: null,
    user: null,
    management: null,
    users: [],
    user_events: [],
    error: "",
  });
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
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [archivedConversations, setArchivedConversations] = useState<Conversation[]>([]);
  const [activeConversationId, setActiveConversationId] = useState<number | string | null>(null);
  const [sidebarExpanded, setSidebarExpanded] = useState(true);
  const [privateMode, setPrivateMode] = useState(false);
  const [showArchived, setShowArchived] = useState(false);
  const [input, setInput] = useState("");
  const [visionMessage, setVisionMessage] = useState("HAND TRACKING · MAXIMIZE TO ENABLE");
  const chatEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handler = (event: Event) => {
      const detail = (event as CustomEvent<AuthState>).detail;
      setAuth({ ...detail, ready: true });
      setPrivateMode(Boolean(detail.private_mode));
      if (detail.required) {
        setMessages([]);
        setConversations([]);
        setArchivedConversations([]);
        setActiveConversationId(null);
      } else if (Array.isArray(detail.history)) {
        setMessages(detail.history);
        setActiveConversationId(detail.active_conversation_id ?? null);
      }
    };
    window.addEventListener("jarvisAuth", handler);
    return () => window.removeEventListener("jarvisAuth", handler);
  }, []);

  useEffect(() => {
    const handler = (event: Event) => {
      const detail = (event as CustomEvent<{
        items: Conversation[];
        archived_items?: Conversation[];
        active_id: number | string | null;
      }>).detail;
      setConversations(detail.items || []);
      setArchivedConversations(detail.archived_items || []);
      setActiveConversationId(detail.active_id ?? null);
    };
    window.addEventListener("jarvisConversations", handler);
    return () => window.removeEventListener("jarvisConversations", handler);
  }, []);

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
      if (typeof s.private_mode === "boolean") setPrivateMode(s.private_mode);
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
  const authSend = (data: object) => window.dispatchEvent(new CustomEvent("jarvisAuthAction", { detail: data }));
  const closeApp = () => authSend({ do: "close_app" });
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
    ? "MIC MUTED · SAY JARVIS UNMUTE"
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
  const canManageUsers = auth.user?.role === "admin";
  const displayedConversations = showArchived ? archivedConversations : conversations;

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

  if (!auth.ready || auth.required || !auth.user) {
    return <AuthScreen key={`${auth.mode}-${auth.setup}`} auth={auth} send={authSend} close={closeApp} />;
  }
  if (!auth.user.gender) {
    return <GenderSetup auth={auth} send={authSend} close={closeApp} />;
  }

  return (
    <>
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

      <motion.aside
        animate={{ width: sidebarExpanded ? 256 : 54 }}
        transition={{ duration: 0.2, ease: "easeOut" }}
        style={{
          position: "fixed",
          top: 92,
          bottom: 28,
          left: 24,
          zIndex: 120,
          display: "flex",
          flexDirection: "column",
          gap: 12,
          boxSizing: "border-box",
          padding: 10,
          overflow: "hidden",
          borderRadius: 16,
          color: "#d4fbff",
          background: "linear-gradient(145deg, rgba(10,31,42,0.84), rgba(3,10,17,0.78))",
          border: "1px solid rgba(34,229,255,0.18)",
          boxShadow: "0 14px 40px rgba(0,0,0,0.4), inset 0 1px rgba(255,255,255,0.08)",
          backdropFilter: "blur(22px) saturate(145%)",
          WebkitBackdropFilter: "blur(22px) saturate(145%)",
        }}
        aria-label="Previous discussions"
      >
        <div style={{ display: "flex", alignItems: "center", gap: 7, minHeight: 34 }}>
          <button
            type="button"
            onClick={() => setSidebarExpanded((expanded) => !expanded)}
            aria-label={sidebarExpanded ? "Collapse discussions sidebar" : "Expand discussions sidebar"}
            title={sidebarExpanded ? "Collapse sidebar" : "Expand sidebar"}
            style={discussionIconButton}
          >
            {sidebarExpanded ? <PanelLeftClose size={17} /> : <PanelLeftOpen size={17} />}
          </button>
          {sidebarExpanded && (
            <>
              <span style={{ flex: 1, color: "rgba(190,239,255,0.72)", fontSize: 10, letterSpacing: "0.12em" }}>
                {showArchived ? "ARCHIVED" : "DISCUSSIONS"}
              </span>
              <button
                type="button"
                onClick={() => authSend({ do: "new_conversation" })}
                aria-label="Create a new discussion"
                title="New discussion"
                style={discussionIconButton}
              >
                <Plus size={17} />
              </button>
            </>
          )}
        </div>
        {sidebarExpanded && (
          <>
            <div style={{ display: "flex", gap: 6 }}>
              <button
                type="button"
                onClick={() => authSend({ do: "set_private_mode", enabled: !privateMode })}
                aria-pressed={privateMode}
                title={privateMode
                  ? "History is saved only on this computer; your selected AI provider may still process messages."
                  : "Switch to local-only chat history"}
                style={{
                  ...authSecondaryButton,
                  flex: 1,
                  padding: "8px 7px",
                  borderColor: privateMode ? "rgba(34,229,255,0.5)" : "rgba(34,229,255,0.16)",
                  color: privateMode ? CYAN : "rgba(190,239,255,0.68)",
                }}
              >
                <Shield size={13} style={{ verticalAlign: "middle", marginRight: 5 }} />
                {privateMode ? "PRIVATE · LOCAL" : "CLOUD"}
              </button>
              <button
                type="button"
                onClick={() => authSend({ do: "archive_history" })}
                aria-label="Archive all discussions"
                title="Hide all conversations in Archived"
                style={discussionIconButton}
              >
                <Archive size={15} />
              </button>
            </div>
            <button
              type="button"
              onClick={() => setShowArchived((shown) => !shown)}
              style={{
                ...authSecondaryButton,
                padding: "7px 9px",
                textAlign: "left",
                color: showArchived ? CYAN : "rgba(190,239,255,0.62)",
              }}
            >
              {showArchived ? "← BACK TO DISCUSSIONS" : `ARCHIVED · ${archivedConversations.length}`}
            </button>
          </>
        )}
        {!sidebarExpanded && (
          <button
            type="button"
            onClick={() => authSend({ do: "new_conversation" })}
            aria-label="Create a new discussion"
            title="New discussion"
            style={discussionIconButton}
          >
            <Plus size={17} />
          </button>
        )}
        {sidebarExpanded && (
          <div className="jv-scroll" style={{ display: "grid", alignContent: "start", gap: 6, overflowY: "auto", flex: 1 }}>
            {displayedConversations.map((conversation) => (
              <div key={conversation.id} style={{ display: "flex", gap: 4 }}>
                <button
                  type="button"
                  onClick={() => authSend({ do: "open_conversation", conversation_id: conversation.id })}
                  title={conversation.title}
                  aria-current={activeConversationId === conversation.id ? "page" : undefined}
                  style={{
                    flex: 1,
                    minWidth: 0,
                    padding: "10px 9px",
                    overflow: "hidden",
                    borderRadius: 9,
                    border: `1px solid ${activeConversationId === conversation.id ? "rgba(34,229,255,0.3)" : "transparent"}`,
                    color: activeConversationId === conversation.id ? "#e5fcff" : "rgba(190,239,255,0.68)",
                    background: activeConversationId === conversation.id ? "rgba(34,229,255,0.1)" : "transparent",
                    textAlign: "left",
                    font: `11px ${MONO}`,
                    whiteSpace: "nowrap",
                    textOverflow: "ellipsis",
                    cursor: "pointer",
                  }}
                >
                  <span style={{ display: "block", overflow: "hidden", textOverflow: "ellipsis" }}>
                    {conversation.private && <Shield size={12} style={{ verticalAlign: "middle", marginRight: 5 }} />}
                    {conversation.title}
                  </span>
                </button>
                {showArchived && (
                  <button
                    type="button"
                    aria-label="Restore discussion"
                    title="Restore discussion"
                    onClick={() => authSend({ do: "restore_conversation", conversation_id: conversation.id })}
                    style={discussionIconButton}
                  >
                    <RotateCcw size={13} />
                  </button>
                )}
              </div>
            ))}
            {displayedConversations.length === 0 && (
              <span style={{ padding: 8, color: "rgba(190,239,255,0.4)", fontSize: 10, lineHeight: 1.5 }}>
                {showArchived ? "No archived discussions" : "No previous discussions"}
              </span>
            )}
          </div>
        )}
        {sidebarExpanded && (
          <button
            type="button"
            onClick={() => authSend({ do: "open_permanent_delete_history" })}
            style={{
              ...authSecondaryButton,
              padding: "8px 9px",
              textAlign: "left",
              borderColor: "rgba(255,84,112,0.3)",
              color: "#ff9aaa",
            }}
          >
            <Trash2 size={13} style={{ verticalAlign: "middle", marginRight: 6 }} />
            PERMANENTLY DELETE HISTORY
          </button>
        )}
      </motion.aside>

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
                        opacity: statusLabel === "STANDBY" || statusLabel === "MIC MUTED · SAY JARVIS UNMUTE" || !isOnline ? 0.35 : 1,
                        animation:
                          statusLabel === "STANDBY" || statusLabel === "MIC MUTED · SAY JARVIS UNMUTE" || !isOnline
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
      <div
        style={{
          position: "fixed",
          top: 34,
          left: 28,
          zIndex: 100,
          display: "flex",
          alignItems: "center",
          gap: 8,
          fontFamily: MONO,
        }}
      >
        <span style={{ color: CYAN, fontSize: 10, letterSpacing: "0.12em" }}>
          {auth.user.username.toUpperCase()} · {auth.user.role.toUpperCase()}
        </span>
        {canManageUsers && (
          <>
            <button onClick={() => authSend({ do: "open_add_user" })} style={authSecondaryButton}>
              ADD USER
            </button>
            <button onClick={() => authSend({ do: "open_delete_user" })} style={authSecondaryButton}>
              USERS
            </button>
          </>
        )}
        <button onClick={() => authSend({ do: "logout" })} style={authSecondaryButton}>
          END SESSION
        </button>
      </div>
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
    <UserManagementDialog
      key={`${auth.management?.mode || ""}-${auth.management?.step || ""}-${auth.management?.username || ""}`}
      auth={auth}
      send={authSend}
    />
    <PendingActionDialog
      key={`${auth.pending_action?.stage || ""}-${auth.pending_action?.label || ""}`}
      auth={auth}
      send={authSend}
    />
    </>
  );
}