"use client";

import { createContext, useContext, useEffect, useRef, useState } from "react";

import { api, type RegisterInput, type User } from "@/lib/api";

type AuthContextValue = {
  user: User | null;
  accessToken: string | null;
  loading: boolean;
  register: (input: RegisterInput) => Promise<void>;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [accessToken, setAccessToken] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const restored = useRef(false);

  useEffect(() => {
    if (restored.current) return;
    restored.current = true;
    api
      .refresh()
      .then(async (token) => {
        setAccessToken(token.access_token);
        setUser(await api.me(token.access_token));
      })
      .catch(() => {
        setAccessToken(null);
        setUser(null);
      })
      .finally(() => setLoading(false));
  }, []);

  async function login(email: string, password: string) {
    const token = await api.login(email, password);
    const currentUser = await api.me(token.access_token);
    setAccessToken(token.access_token);
    setUser(currentUser);
  }

  async function register(input: RegisterInput) {
    await api.register(input);
    await login(input.email, input.password);
  }

  async function logout() {
    try {
      await api.logout();
    } finally {
      setAccessToken(null);
      setUser(null);
    }
  }

  return (
    <AuthContext.Provider
      value={{ user, accessToken, loading, register, login, logout }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside AuthProvider");
  return context;
}
