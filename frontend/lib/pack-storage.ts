import type { SourceDocument } from "./knowledge-pack";

export interface SavedPack {
  id: string;
  name: string;
  updatedAt: string;
  documents: SourceDocument[];
  options: { chunkSize: number; overlap: number; removeRepeatedHeaders: boolean };
}

async function database(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open("taffybop-knowledge-studio", 1);
    request.onupgradeneeded = () => request.result.createObjectStore("packs", { keyPath: "id" });
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(new Error("Device storage is unavailable. You can still download your pack."));
  });
}

export async function listSavedPacks(): Promise<SavedPack[]> {
  const db = await database();
  try {
    return await new Promise((resolve, reject) => {
      const request = db.transaction("packs", "readonly").objectStore("packs").getAll();
      request.onsuccess = () => resolve((request.result as SavedPack[]).sort((a, b) => b.updatedAt.localeCompare(a.updatedAt)));
      request.onerror = () => reject(request.error);
    });
  } finally { db.close(); }
}

export async function writeSavedPack(pack: SavedPack): Promise<void> {
  const db = await database();
  try {
    await new Promise<void>((resolve, reject) => {
      const transaction = db.transaction("packs", "readwrite");
      transaction.objectStore("packs").put(pack);
      transaction.oncomplete = () => resolve();
      transaction.onerror = () => reject(new Error("Could not save on this device. Storage may be full; download a backup instead."));
      transaction.onabort = () => reject(new Error("Saving was interrupted. Download a backup and try again."));
    });
  } finally { db.close(); }
}

export async function deleteSavedPack(id: string): Promise<void> {
  const db = await database();
  try {
    await new Promise<void>((resolve, reject) => {
      const transaction = db.transaction("packs", "readwrite");
      transaction.objectStore("packs").delete(id);
      transaction.oncomplete = () => resolve();
      transaction.onerror = () => reject(new Error("Could not delete this pack. Please try again."));
      transaction.onabort = () => reject(new Error("Deleting was interrupted. Please try again."));
    });
  } finally { db.close(); }
}
