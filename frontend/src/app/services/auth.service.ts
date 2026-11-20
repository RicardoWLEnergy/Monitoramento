import { Injectable, computed, inject, signal } from '@angular/core';
import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { Observable, firstValueFrom, map } from 'rxjs';

export type Perfil = 'admin' | 'colaborador' | 'cliente';

export interface Usuario {
  id: number;
  id_cliente: string | null;
  /** Usinas ativas vinculadas (cliente sem usina = ainda em instalação). */
  qtd_usinas: number;
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

/** Resposta de "enviar código pelo WhatsApp". */
export interface CodigoEnviado { detail: string; numero: string; validade_minutos: number; reenvio_segundos: number; }

const CHAVE_TOKENS = 'wl-tokens';
const CANAL_SESSAO = 'wl-sessao';
type MensagemSessao = { tipo: 'pedir' } | { tipo: 'tokens'; tokens: Tokens } | { tipo: 'sair' };

export const ROTULO_PERFIL: Record<Perfil, string> = {
  admin: 'Admin', colaborador: 'Colaborador', cliente: 'Cliente',
};

/**
 * Login com a API Django (JWT).
 * - access: vale 30 min e vai em toda requisição (ver auth.interceptor.ts)
 * - refresh: vale no máximo 12 h e serve para pegar um novo access sem pedir a senha de novo
 *
 * Os tokens ficam no sessionStorage: FECHAR O NAVEGADOR (ou todas as guias do sistema) ENCERRA A SESSÃO.
 * Guias abertas ao mesmo tempo compartilham o login por um BroadcastChannel: a guia nova pede os
 * tokens às outras; sair numa guia sai de todas.
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
  /** Cliente com usina ligada (vê "Usinas"); a equipe sempre vê. */
  readonly temUsinas = computed(() => this.eEquipe() || (this._usuario()?.qtd_usinas ?? 0) > 0);
  /** Cliente com ID (nº da obra): vê "Meu projeto". */
  readonly temProjeto = computed(() => !this.eEquipe() && !!this._usuario()?.id_cliente);
  readonly iniciais = computed(() =>
    (this._usuario()?.nome ?? '').split(' ').filter(Boolean).slice(0, 2).map(p => p[0].toUpperCase()).join(''));

  private readonly canal = typeof BroadcastChannel !== 'undefined' ? new BroadcastChannel(CANAL_SESSAO) : null;
  /** Enquanto esta guia espera os tokens de outra guia aberta. */
  private aoChegarTokens: (() => void) | null = null;

  constructor() {
    try { localStorage.removeItem(CHAVE_TOKENS); } catch { /* ignora */ }   // logins antigos, guardados sem prazo
    this.canal?.addEventListener('message', e => this.aoReceber(e.data as MensagemSessao));
  }

  /** Chamado ao abrir o app: recupera o usuário com os tokens desta guia ou de outra guia aberta. */
  async iniciar(): Promise<void> {
    if (!this.tokens()) await this.pedirTokensDasOutrasGuias();
    if (!this.tokens()) return;
    try {
      await this.carregarUsuario();
    } catch (erro) {
      // Só encerra o login se o servidor recusar; queda de rede/atualização do servidor não desloga as guias
      if (erro instanceof HttpErrorResponse && (erro.status === 401 || erro.status === 403)) this.sair();
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

  /** Envia um código de 6 números para o WhatsApp cadastrado no e-mail. */
  async pedirCodigo(email: string): Promise<CodigoEnviado> {
    try {
      return await firstValueFrom(this.http.post<CodigoEnviado>('/api/auth/codigo/', { email: email.trim() }));
    } catch (erro) {
      throw new Error(mensagemDeErro(erro, 'Não foi possível enviar o código.'));
    }
  }

  async entrarComCodigo(email: string, codigo: string): Promise<void> {
    try {
      const tokens = await firstValueFrom(
        this.http.post<Tokens>('/api/auth/codigo/entrar/', { email: email.trim(), codigo: codigo.trim() }));
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

  /** Sai nesta guia e nas outras guias abertas. */
  sair(): void {
    this.limpar();
    this.canal?.postMessage({ tipo: 'sair' } satisfies MensagemSessao);
  }

  tokenAcesso(): string | null { return this.tokens()?.access ?? null; }
  tokenRenovacao(): string | null { return this.tokens()?.refresh ?? null; }

  private limpar(): void {
    this._usuario.set(null);
    try { sessionStorage.removeItem(CHAVE_TOKENS); } catch { /* ignora */ }
  }

  private aoReceber(m: MensagemSessao): void {
    if (m.tipo === 'pedir') {
      const tokens = this.tokens();
      if (tokens) this.canal?.postMessage({ tipo: 'tokens', tokens } satisfies MensagemSessao);
    } else if (m.tipo === 'tokens' && this.aoChegarTokens) {
      this.salvarTokens(m.tokens);
      this.aoChegarTokens();
    } else if (m.tipo === 'sair' && this.tokens()) {
      this.limpar();
      window.location.assign('/login');
    }
  }

  /** Guia nova: pergunta às guias abertas se já há login (espera no máximo 300 ms). */
  private pedirTokensDasOutrasGuias(): Promise<void> {
    if (!this.canal) return Promise.resolve();
    return new Promise(resolve => {
      const terminar = () => { clearTimeout(limite); this.aoChegarTokens = null; resolve(); };
      const limite = setTimeout(terminar, 300);
      this.aoChegarTokens = terminar;
      this.canal!.postMessage({ tipo: 'pedir' } satisfies MensagemSessao);
    });
  }

  private tokens(): Tokens | null {
    try {
      const bruto = sessionStorage.getItem(CHAVE_TOKENS);
      return bruto ? (JSON.parse(bruto) as Tokens) : null;
    } catch {
      return null;
    }
  }

  private salvarTokens(tokens: Tokens): void {
    try { sessionStorage.setItem(CHAVE_TOKENS, JSON.stringify(tokens)); } catch { /* ignora */ }
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
