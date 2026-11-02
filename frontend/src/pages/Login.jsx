import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api, setToken, errMsg } from "@/lib/api";

export default function Login() {
  const nav = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    document.documentElement.classList.toggle("dark", localStorage.getItem("bc_theme") !== "light");
  }, []);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setErr("");
    try {
      const r = await api.post("/auth/login", { email, password });
      setToken(r.data.token);
      nav("/");
    } catch (e2) {
      setErr(errMsg(e2));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="grid min-h-screen lg:grid-cols-2">
      <div className="relative hidden overflow-hidden bg-[hsl(var(--sidebar))] lg:block">
        <img src="https://images.unsplash.com/photo-1594300157693-a741f98738c2?crop=entropy&cs=srgb&fm=jpg&q=70&w=1400" alt="Melbourne" className="absolute inset-0 h-full w-full object-cover opacity-30" />
        <div className="absolute inset-0 grid-bg opacity-40" />
        <div className="relative flex h-full flex-col justify-end p-12 text-white">
          <div className="eyebrow mb-3 !text-cyan-300">Internal business development</div>
          <h1 className="max-w-md font-display text-5xl font-extrabold leading-tight tracking-tight">Find the local businesses that need you.</h1>
          <p className="mt-4 max-w-md text-slate-300">Discover, assess and reach out to Australian brick-and-mortar businesses — and watch the agent work in real time.</p>
        </div>
      </div>
      <div className="flex items-center justify-center p-6">
        <form onSubmit={submit} className="w-full max-w-sm space-y-5" data-testid="login-form">
          <div className="flex items-center gap-3">
            <div className="grid h-10 w-10 place-items-center rounded-md bg-cyan-500 font-display font-extrabold text-slate-950">BC</div>
            <div>
              <div className="font-display text-lg font-bold">Bright Coda Local Business Scout</div>
              <div className="text-xs text-muted-foreground">Administrator sign in</div>
            </div>
          </div>
          <Input data-testid="login-email-input" type="email" placeholder="Email" value={email} onChange={(e) => setEmail(e.target.value)} required />
          <Input data-testid="login-password-input" type="password" placeholder="Password" value={password} onChange={(e) => setPassword(e.target.value)} required />
          {err && <div data-testid="login-error" className="text-sm text-red-500">{err}</div>}
          <Button data-testid="login-submit-button" className="w-full" disabled={busy}>
            {busy && <Loader2 className="mr-2 h-4 w-4 animate-spin" />} Sign in
          </Button>
        </form>
      </div>
    </div>
  );
}
