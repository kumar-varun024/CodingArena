import { spawn, type ChildProcess } from 'node:child_process';

export async function startFixture(): Promise<{ baseUrl: string; close: () => void }> {
  const child: ChildProcess = spawn('python3', ['-u', '-c', "from mock.server import create_server; s=create_server('127.0.0.1',0); print(s.server_address[1],flush=True); s.serve_forever()"], { cwd: process.cwd(), stdio: ['ignore', 'pipe', 'pipe'] });
  const port = await new Promise<number>((resolve, reject) => {
    let output = '';
    const timer = setTimeout(() => { child.kill(); reject(new Error('Fixture server startup timed out.')); }, 5000);
    child.on('error', error => { clearTimeout(timer); reject(error); });
    child.stdout!.on('data', chunk => { output += String(chunk); const match = output.match(/^(\d+)\n/); if (match) { clearTimeout(timer); resolve(Number(match[1])); } });
    child.stderr!.on('data', chunk => { if (String(chunk).includes('Traceback')) { clearTimeout(timer); reject(new Error(String(chunk))); } });
  });
  return { baseUrl: `http://127.0.0.1:${port}/api/v1`, close: () => { child.kill(); } };
}
