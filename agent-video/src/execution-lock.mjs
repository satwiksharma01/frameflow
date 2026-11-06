import { createServer } from 'node:net';
import { createHash } from 'node:crypto';
import { realpath } from 'node:fs/promises';

export async function withBatchLock(directory, action) {
  const canonical = await realpath(directory);
  const identity = process.platform === 'win32' ? canonical.toLowerCase() : canonical;
  const hash = createHash('sha256').update(identity).digest('hex');
  const endpoint = process.platform === 'win32'
    ? { path: `\\\\.\\pipe\\agent-video-batch-${hash}`, exclusive: true }
    : { host: '127.0.0.1', port: 49152 + parseInt(hash.slice(0, 4), 16) % 16384, exclusive: true };
  // The OS releases this endpoint on exit; no stale lock file or PID is trusted.
  const server = createServer(socket => socket.destroy());
  await new Promise((resolve, reject) => {
    server.once('error', error => reject(error.code === 'EADDRINUSE'
      ? Object.assign(new Error(`This batch is already running: ${canonical}`), { code: 'BATCH_BUSY' })
      : error));
    server.listen(endpoint, resolve);
  });
  try { return await action(); }
  finally {
    await new Promise((resolve, reject) => server.close(error => error ? reject(error) : resolve()));
  }
}
