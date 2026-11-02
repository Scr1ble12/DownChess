// The bridge between the page and the main process: Stockfish processes and web requests.

const { contextBridge, ipcRenderer } = require('electron');

const listeners = new Map();
ipcRenderer.on('engine:lines', (_e, id, lines) => {
  const cb = listeners.get(id);
  if (cb) for (const line of lines) cb(line);
});

contextBridge.exposeInMainWorld('downchess', {
  engine: {
    start() {
      const r = ipcRenderer.sendSync('engine:start');
      if (r.error) throw new Error(r.error);
      return r.id;
    },
    send: (id, cmd) => ipcRenderer.send('engine:send', id, cmd),
    onLine: (id, cb) => { listeners.set(id, cb); },
    stop: id => { listeners.delete(id); ipcRenderer.send('engine:stop', id); },
  },
  fetch: (url, opts) => ipcRenderer.invoke('net:fetch', url, { headers: opts?.headers }),
});
