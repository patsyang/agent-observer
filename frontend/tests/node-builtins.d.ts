type BufferEncoding = 'utf-8' | 'utf8';

declare module 'node:child_process' {
  export function execFileSync(command: string, args?: string[], options?: { cwd?: string; encoding?: BufferEncoding }): string;
}

declare module 'node:fs' {
  export function mkdirSync(path: string, options?: { recursive?: boolean }): void;
  export function readFileSync(path: string, encoding: BufferEncoding): string;
  export function rmSync(path: string, options?: { recursive?: boolean; force?: boolean }): void;
  export function writeFileSync(path: string, data: string | Uint8Array): void;
}

declare module 'node:path' {
  export function join(...parts: string[]): string;
}
