type BufferEncoding = 'utf-8' | 'utf8';
type Buffer = { toString(encoding?: BufferEncoding): string };
type ChildProcess = {
  stdout: { on(event: 'data', listener: (chunk: Buffer) => void): void };
  stderr: { on(event: 'data', listener: (chunk: Buffer) => void): void };
  on(event: 'error', listener: (error: Error) => void): void;
  on(event: 'close', listener: () => void): void;
  kill(): void;
};

declare module 'node:child_process' {
  export function execFileSync(command: string, args?: string[], options?: { cwd?: string; encoding?: BufferEncoding }): string;
  export function spawn(command: string, args?: string[], options?: { cwd?: string; windowsHide?: boolean }): ChildProcess;
}

declare module 'node:fs' {
  export function mkdirSync(path: string, options?: { recursive?: boolean }): void;
  export function readFileSync(path: string, encoding: BufferEncoding): string;
  export function rmSync(path: string, options?: { recursive?: boolean; force?: boolean }): void;
  export function writeFileSync(path: string, data: string | Uint8Array | Buffer): void;
}

declare module 'node:path' {
  export function join(...parts: string[]): string;
}
