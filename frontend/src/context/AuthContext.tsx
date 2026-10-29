import React, { createContext, useContext, useState, useEffect } from 'react';
import type { User } from '../types';
import { authApi } from '../api/client';
import { ensureInbox } from '../lib/secureInbox';

/** Set up the institution's encrypted inbox in the background; never blocks sign-in. */
const withInbox = (u: User) => { ensureInbox(u).catch((e) => console.warn('Secure inbox setup failed', e)); return u; };

interface AuthContextType {
  user: User | null;
  token: string | null;
  isLoading: boolean;
  login: (email: string, pass: string) => Promise<void>;
  logout: () => void;
  isAuthenticated: boolean;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<User | null>(null);
  const [token, setToken] = useState<string | null>(localStorage.getItem('aicte_token'));
  const [isLoading, setIsLoading] = useState<boolean>(true);

  useEffect(() => {
    const fetchUser = async () => {
      const storedToken = localStorage.getItem('aicte_token');
      if (storedToken) {
        try {
          const profile = await authApi.getMe();
          setUser(withInbox(profile));
        } catch {
          localStorage.removeItem('aicte_token');
          setToken(null);
          setUser(null);
        }
      }
      setIsLoading(false);
    };
    fetchUser();
  }, []);

  const login = async (email: string, pass: string) => {
    const data = await authApi.login({ email, password: pass });
    localStorage.setItem('aicte_token', data.access_token);
    setToken(data.access_token);
    const profile = await authApi.getMe();
    setUser(withInbox(profile));
  };

  const logout = () => {
    localStorage.removeItem('aicte_token');
    setToken(null);
    setUser(null);
  };

  return (
    <AuthContext.Provider
      value={{
        user,
        token,
        isLoading,
        login,
        logout,
        isAuthenticated: !!user,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};
