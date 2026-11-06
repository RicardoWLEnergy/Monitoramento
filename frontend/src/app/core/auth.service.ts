import { Injectable, computed, signal } from '@angular/core';

export type Perfil = 'admin' | 'tecnico' | 'cliente';

export interface Usuario {
  nome: string;
  email: string;
  perfil: Perfil;
}

const CHAVE = 'wl-sessao';

/**
 * Autenticação SIMULADA (sem backend).
 * Aceita qualquer e-mail + senha preenchidos e entra como Admin.
 * Será substituída pelo login JWT do Django quando o backend for retomado.
 */
@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly _usuario = signal<Usuario | null>(this.lerSessao());

  readonly usuario = this._usuario.asReadonly();
  readonly logado = computed(() => this._usuario() !== null);
  readonly iniciais = computed(() => {
    const nome = this._usuario()?.nome ?? '';
    return nome.split(' ').filter(Boolean).slice(0, 2).map(p => p[0].toUpperCase()).join('');
  });

  async entrar(email: string, senha: string): Promise<void> {
    await new Promise(r => setTimeout(r, 500)); // simula latência da API
    if (!email.trim() || !senha) {
      throw new Error('Informe e-mail e senha.');
    }
    const usuario: Usuario = { nome: 'Administrador WL', email: email.trim(), perfil: 'admin' };
    this._usuario.set(usuario);
    try { localStorage.setItem(CHAVE, JSON.stringify(usuario)); } catch { /* ignora */ }
  }

  sair(): void {
    this._usuario.set(null);
    try { localStorage.removeItem(CHAVE); } catch { /* ignora */ }
  }

  private lerSessao(): Usuario | null {
    try {
      const bruto = localStorage.getItem(CHAVE);
      return bruto ? (JSON.parse(bruto) as Usuario) : null;
    } catch {
      return null;
    }
  }
}
