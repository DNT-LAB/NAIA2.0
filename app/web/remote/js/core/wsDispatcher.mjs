export function createWsMessageDispatcher({
  BlobClass,
  onBlob,
  handlers,
  afterJson,
  onError,
}) {
  return event => {
    if (event.data instanceof BlobClass) {
      onBlob(event.data);
      return;
    }

    try {
      const message = JSON.parse(event.data);
      const handler = handlers[message.type];
      if (handler) handler(message);
      if (afterJson) afterJson(message);
    } catch (error) {
      if (onError) onError(error, event.data);
    }
  };
}
