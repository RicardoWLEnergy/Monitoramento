import { Injectable, computed, inject, signal } from '@angular/core';
import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { Observable, firstValueFrom, map } from 'rxjs';

export type Perfil = 'admin' | 'colaborador' | 'cliente';

export interface Usuario {
  id: number;
  email: string;
  nome: string;
  whatsapp: string | null;
  cpf_formatado: string;
  endereco: string;
  link_maps: string | null;
  perfil: Perfil;
  last_login: string | null;
}

interface Tokens { access: string; refresh: string; }

const CHAVE_TOKENS = 'wl-tokens';

export const ROTULO_PERFIL: Record<Perfil, string> = {
  admin: 'Admin', colaborador: 'Colaborador', cliente: 'Cliente',
};

/**
 * Login com a API Django (JWT).
 * - access: vale 30 min e vai em toda requisição (ver auth.interceptor.ts)
 * - refresh: vale 7 dias e serve para pegar um novo access sem pedir a senha de novo
 */
@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly http = inject(HttpClient);
  private readonly _usuario = signal<Usuario | null>(null);

  readonly usuario = this._usuario.asReadonly();
  readonly logado = computed(() => this._usuario() !== null);
  readonly perfil = computed(() => this._usuario()?.perfil ?? null);
  /** Admin ou Colaborador (equipe WL). */
  readonly eEquipe = computed(() => this.perfil() === 'admin' || this.perfil() === 'colaborador');
  readonly eAdmin = computed(() => this.perfil() === 'admin');
  readonly iniciais = computed(() =>
    (this._usuario()?.nome ?? '').split(' ').filter(Boolean).slice(0, 2).map(p => p[0].toUpperCase()).join(''));

  /** Chamado ao abrir o app: se houver tokens salvos, recupera o usuário. */
  async iniciar(): Promise<void> {
    if (!this.tokens()) return;
    try {
      await this.carregarUsuario();
    } catch {
      this.sair();
    }
  }

  async entrar(email: string, senha: string): Promise<void> {
    try {
      const tokens = await firstValueFrom(
        this.http.post<Tokens>('/api/auth/login/', { email: email.trim(), password: senha }));
      this.salvarTokens(tokens);
      await this.carregarUsuario();
    } catch (erro) {
      throw new Error(mensagemDeErro(erro, 'Não foi possível entrar.'));
    }
  }

  async carregarUsuario(): Promise<void> {
    this._usuario.set(await firstValueFrom(this.http.get<Usuario>('/api/auth/eu/')));
  }

  /** Troca o refresh por um novo access (usado pelo interceptor quando recebe 401). */
  renovar(): Observable<string> {
    return this.http.post<{ access: string }>('/api/auth/renovar/', { refresh: this.tokens()?.refresh })
      .pipe(map(r => {
        this.salvarTokens({ ...this.tokens()!, access: r.access });
        return r.access;
      }));
  }

  sair(): void {
    this._usuario.set(null);
    try { localStorage.removeItem(CHAVE_TOKENS); } catch { /* ignora */ }
  }

  tokenAcesso(): string | null { return this.tokens()?.access ?? null; }
  tokenRenovacao(): string | null { return this.tokens()?.refresh ?? null; }

  private tokens(): Tokens | null {
    try {
      const bruto = localStorage.getItem(CHAVE_TOKENS);
      return bruto ? (JSON.parse(bruto) as Tokens) : null;
    } catch {
      return null;
    }
  }

  private salvarTokens(tokens: Tokens): void {
    try { localStorage.setItem(CHAVE_TOKENS, JSON.stringify(tokens)); } catch { /* ignora */ }
  }
}

/** Extrai uma mensagem legível de um erro da API (DRF). */
export function mensagemDeErro(erro: unknown, padrao = 'Algo deu errado.'): string {
  if (!(erro instanceof HttpErrorResponse)) return erro instanceof Error ? erro.message : padrao;
  if (erro.status === 0) return 'Sem conexão com o servidor.';
  const corpo = erro.error;
  if (corpo?.detail) return corpo.detail;
  if (corpo && typeof corpo === 'object') {
    const [campo, msgs] = Object.entries(corpo)[0] ?? [];
    if (campo) return `${campo}: ${Array.isArray(msgs) ? msgs.join(' ') : msgs}`;
  }
  return padrao;
}
