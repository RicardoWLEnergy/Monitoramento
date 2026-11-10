import { Injectable, signal } from '@angular/core';

export type Tema = 'claro' | 'escuro';

const CHAVE = 'wl-tema';

/** Tema por pessoa, salvo no localStorage e aplicado em <html data-theme>. */
@Injectable({ providedIn: 'root' })
export class TemaService {
  readonly tema = signal<Tema>(this.lerSalvo());

  alternar(): void {
    this.definir(this.tema() === 'claro' ? 'escuro' : 'claro');
  }

  definir(tema: Tema): void {
    this.tema.set(tema);
    document.documentElement.setAttribute('data-theme', tema);
    try { localStorage.setItem(CHAVE, tema); } catch { /* storage indisponível */ }
  }

  private lerSalvo(): Tema {
    try {
      return localStorage.getItem(CHAVE) === 'escuro' ? 'escuro' : 'claro';
    } catch {
      return 'claro';
    }
  }
}
