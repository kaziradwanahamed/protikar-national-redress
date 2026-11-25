/* IndexedDB Offline Queue + Auto-Sync + <140-Byte 2G SMS Fallback for Field Workers */
const DB_NAME = "bd_grievance_field_v1";
const STORE_NAME = "pending_resolutions";
const MAX_2G_SMS_BYTES = 140;

function openFieldDB() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, 1);
    req.onupgradeneeded = (evt) => {
      const db = evt.target.result;
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        db.createObjectStore(STORE_NAME, { keyPath: "local_id" });
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function enqueueOfflineResolution(record) {
  const db = await openFieldDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, "readwrite");
    tx.objectStore(STORE_NAME).put(record);
    tx.oncomplete = () => resolve(record);
    tx.onerror = () => reject(tx.error);
  });
}

async function listOfflineResolutions() {
  const db = await openFieldDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, "readonly");
    const req = tx.objectStore(STORE_NAME).getAll();
    req.onsuccess = () => resolve(req.result || []);
    req.onerror = () => reject(req.error);
  });
}

async function removeOfflineResolution(localId) {
  const db = await openFieldDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, "readwrite");
    tx.objectStore(STORE_NAME).delete(localId);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}

function getCookie(name) {
  const match = document.cookie.match(new RegExp("(^| )" + name + "=([^;]+)"));
  return match ? decodeURIComponent(match[2]) : "";
}

/**
 * Generate a strict <=140-byte UTF-8 compact 2G SMS payload when mobile data fails.
 * Grammar: RES#<tracking_code>#<lat>,<lon>#<summary>
 */
function generateCompact2GSMS({ trackingCode, lat, lon, workSummary }) {
  const prefix = `RES#${(trackingCode || "CASE").trim()}#${Number(lat).toFixed(4)},${Number(lon).toFixed(4)}#`;
  const encoder = new TextEncoder();
  const prefixBytes = encoder.encode(prefix).length;
  const budget = Math.max(0, MAX_2G_SMS_BYTES - prefixBytes);

  let cleanSummary = (workSummary || "Fixed").replace(/[
#]+/g, " ").trim();
  while (encoder.encode(cleanSummary).length > budget && cleanSummary.length > 0) {
    cleanSummary = cleanSummary.slice(0, -1);
  }
  const payload = prefix + cleanSummary;
  return {
    payload,
    byteLength: encoder.encode(payload).length,
    smsUri: `sms:333?body=${encodeURIComponent(payload)}`
  };
}

async function syncPendingResolutions() {
  if (!navigator.onLine) {
    return { synced: 0, remaining: (await listOfflineResolutions()).length };
  }
  const items = await listOfflineResolutions();
  let synced = 0;
  for (const item of items) {
    try {
      const resp = await fetch(`/api/v1/workflow/${item.complaint_id}/submit-resolution/`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": getCookie("csrftoken")
        },
        body: JSON.stringify({
          submitted_by_seat: item.submitted_by_seat,
          supervisor_signoff_seat: item.supervisor_signoff_seat,
          work_summary: item.work_summary,
          after_photo_urls: item.after_photo_urls,
          after_lon: Number(item.after_lon),
          after_lat: Number(item.after_lat)
        })
      });
      if (resp.ok || resp.status === 201) {
        await removeOfflineResolution(item.local_id);
        synced += 1;
      }
    } catch (_err) {
      // Remain queued in IndexedDB until connectivity stabilizes
    }
  }
  const remaining = (await listOfflineResolutions()).length;
  return { synced, remaining };
}

window.ProtikarFieldOffline = {
  enqueueOfflineResolution,
  listOfflineResolutions,
  removeOfflineResolution,
  syncPendingResolutions,
  generateCompact2GSMS
};
