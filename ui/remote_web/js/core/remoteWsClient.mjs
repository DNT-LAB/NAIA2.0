import { createWsMessageDispatcher } from './wsDispatcher.mjs';

export function createRemoteWsClient({
  window,
  location,
  WebSocket,
  BlobClass,
  handlers,
  onBlob,
  afterJson,
  onMessageError,
  onSocketChange = () => {},
  onOpen = () => {},
  onClose = () => {},
  reconnectDelayMs = 3000,
}) {
  let socket = null;
  let reconnectTimer = null;

  function clearReconnectTimer() {
    if (!reconnectTimer) return;
    window.clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }

  function setSocket(nextSocket) {
    socket = nextSocket;
    onSocketChange(socket);
  }

  function connect() {
    clearReconnectTimer();
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const nextSocket = new WebSocket(`${proto}//${location.host}/ws`);
    nextSocket.binaryType = 'blob';
    setSocket(nextSocket);

    nextSocket.onopen = () => {
      onOpen(nextSocket);
    };
    nextSocket.onclose = () => {
      onClose(nextSocket);
      reconnectTimer = window.setTimeout(connect, reconnectDelayMs);
    };
    nextSocket.onerror = () => {
      nextSocket.close();
    };
    nextSocket.onmessage = createWsMessageDispatcher({
      BlobClass,
      onBlob,
      handlers,
      afterJson,
      onError: onMessageError,
    });
  }

  function isOpen() {
    return !!socket && socket.readyState === WebSocket.OPEN;
  }

  function sendJson(payload) {
    if (!isOpen()) return false;
    socket.send(JSON.stringify(payload));
    return true;
  }

  return {
    connect,
    isOpen,
    sendJson,
    getSocket: () => socket,
  };
}
