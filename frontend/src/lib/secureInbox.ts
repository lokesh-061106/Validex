/**
 * Institution secure inbox: an RSA-OAEP-2048 key pair generated in this browser with WebCrypto.
 *
 * The private key is created non-extractable and kept in IndexedDB, so it never leaves the
 * browser (not even to JavaScript as raw bytes). The public key (SPKI/PEM) is registered with
 * the server, which encrypts clarification requests to it (RSA-OAEP-SHA256 + AES-256-GCM).
 * Signing in on a new browser rotates the key; requests sent to an older key stay readable only
 * where that key lives, and AICTE can re-issue them.
 */

import { authApi } from '../api/client';
import type { EncryptedEnvelope, User } from '../types';

const DB = 'validex-inbox';
const STORE = 'keys';

const idb = (): Promise<IDBDatabase> =>
  new Promise((resolve, reject) => {
    const req = indexedDB.open(DB, 1);
    req.onupgradeneeded = () => req.result.createObjectStore(STORE);
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });

const tx = async <T>(mode: IDBTransactionMode, fn: (s: IDBObjectStore) => IDBRequest<T>): Promise<T> => {
  const db = await idb();
  return new Promise((resolve, reject) => {
    const r = fn(db.transaction(STORE, mode).objectStore(STORE));
    r.onsuccess = () => resolve(r.result);
    r.onerror = () => reject(r.error);
  });
};

const b64 = (buf: ArrayBuffer) => btoa(String.fromCharCode(...new Uint8Array(buf)));
const unb64 = (s: string) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));

const toPem = (spki: ArrayBuffer) =>
  `-----BEGIN PUBLIC KEY-----\n${b64(spki).match(/.{1,64}/g)!.join('\n')}\n-----END PUBLIC KEY-----\n`;

const normalise = (pem?: string | null) => (pem || '').replace(/\s+/g, '');

async function keyPair(userId: string): Promise<CryptoKeyPair> {
  const existing = await tx<CryptoKeyPair | undefined>('readonly', (s) => s.get(userId));
  if (existing) return existing;
  const generated = await crypto.subtle.generateKey(
    { name: 'RSA-OAEP', modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: 'SHA-256' },
    false, // private key is non-extractable; the public key is always exportable
    ['encrypt', 'decrypt'],
  );
  await tx('readwrite', (s) => s.put(generated, userId));
  return generated;
}

/** Make sure this browser holds a key and the server has its public half. */
export async function ensureInbox(user: User): Promise<void> {
  if (user.role !== 'institution' || !window.crypto?.subtle || !window.indexedDB) return;
  const pair = await keyPair(user.id);
  const pem = toPem(await crypto.subtle.exportKey('spki', pair.publicKey));
  if (normalise(pem) !== normalise(user.public_key_pem)) await authApi.setPublicKey(pem);
}

export async function decryptNotice<T = unknown>(userId: string, env: EncryptedEnvelope): Promise<T> {
  const pair = await tx<CryptoKeyPair | undefined>('readonly', (s) => s.get(userId));
  if (!pair) throw new Error('This browser has no key for your secure inbox.');
  const raw = await crypto.subtle.decrypt({ name: 'RSA-OAEP' }, pair.privateKey, unb64(env.ek));
  const aes = await crypto.subtle.importKey('raw', raw, 'AES-GCM', false, ['decrypt']);
  const plain = await crypto.subtle.decrypt({ name: 'AES-GCM', iv: unb64(env.iv) }, aes, unb64(env.ct));
  return JSON.parse(new TextDecoder().decode(plain)) as T;
}
