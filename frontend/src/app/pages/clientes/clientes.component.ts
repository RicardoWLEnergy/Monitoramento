import { Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { toObservable, toSignal } from '@angular/core/rxjs-interop';
import { RouterLink } from '@angular/router';
import { catchError, debounceTime, firstValueFrom, merge, of, switchMap, tap } from 'rxjs';
import { ChevronLeft, ChevronRight, ExternalLink, LucideAngularModule, Plus, Search, SolarPanel, X } from 'lucide-angular';

import { mensagemDeErro } from '../../services/auth.service';
import { PLATAFORMAS, Pagina, Plataforma } from '../../services/usinas.service';
import { NovoUsuario, ResultadoVinculo, UsuarioCadastro, UsuariosService } from '../../services/usuarios.service';

const POR_PAGINA = 20;

interface Formulario extends Required<Omit<NovoUsuario, 'perfil'>> {
  plataforma: Plataforma;
  sn: string;
}

const formularioVazio = (): Formulario => ({
  nome: '', email: '', cpf: '', whatsapp: '', endereco: '', senha: '', plataforma: 'foxess', sn: '',
});

/**
 * Clientes (Admin e Colaborador).
 * Cadastro = dados do cliente + SN do inversor: o sistema busca a usina na plataforma,
 * grava a usina inteira e vincula ao cliente.
 */
@Component({
  selector: 'app-clientes',
  imports: [FormsModule, RouterLink, LucideAngularModule],
  templateUrl: './clientes.component.html',
  styleUrl: './clientes.component.css',
})
export class ClientesComponent {
  private readonly api = inject(UsuariosService);

  readonly icones = { ChevronLeft, ChevronRight, ExternalLink, Plus, Search, SolarPanel, X };
  readonly plataformas = PLATAFORMAS;

  // ---------- Lista ----------
  readonly busca = signal('');
  readonly pagina = signal(1);
  private readonly recarregar = signal(0);
  readonly carregando = signal(true);

  private readonly filtro = computed(() => ({ busca: this.busca().trim(), page: this.pagina(), _: this.recarregar() }));
  readonly resultado = toSignal(
    toObservable(this.filtro).pipe(
      debounceTime(250),
      tap(() => this.carregando.set(true)),
      switchMap(f => this.api.listar({ perfil: 'cliente', busca: f.busca, page: f.page }).pipe(
        catchError(() => of<Pagina<UsuarioCadastro>>({ count: 0, next: null, previous: null, results: [] })))),
      tap(() => this.carregando.set(false)),
    ),
    { initialValue: null },
  );
  readonly totalPaginas = computed(() => Math.max(1, Math.ceil((this.resultado()?.count ?? 0) / POR_PAGINA)));

  // ---------- Painel: novo cliente / vincular inversor ----------
  readonly modo = signal<'novo' | 'vincular' | null>(null);
  readonly alvo = signal<UsuarioCadastro | null>(null);
  form: Formulario = formularioVazio();
  readonly enviando = signal(false);
  readonly erro = signal<string | null>(null);
  readonly sucesso = signal<{ texto: string; usina?: { id: number; nome: string } } | null>(null);

  definirBusca(v: string): void { this.busca.set(v); this.pagina.set(1); }
  irPara(p: number): void { this.pagina.set(Math.min(Math.max(1, p), this.totalPaginas())); }

  abrirNovo(): void {
    this.form = formularioVazio();
    this.alvo.set(null);
    this.erro.set(null);
    this.sucesso.set(null);
    this.modo.set('novo');
  }

  abrirVincular(cliente: UsuarioCadastro): void {
    this.form = { ...formularioVazio() };
    this.alvo.set(cliente);
    this.erro.set(null);
    this.sucesso.set(null);
    this.modo.set('vincular');
  }

  fechar(): void { this.modo.set(null); }

  async enviar(): Promise<void> {
    this.enviando.set(true);
    this.erro.set(null);
    this.sucesso.set(null);

    // 1) Cria o cliente (só no modo "novo")
    let cliente = this.alvo();
    if (this.modo() === 'novo') {
      try {
        const { plataforma, sn, ...dados } = this.form;
        const novo = { ...limparVazios(dados), perfil: 'cliente' } as NovoUsuario;
        cliente = await firstValueFrom(this.api.criar(novo));
        this.alvo.set(cliente);
        this.modo.set('vincular');   // se a SN falhar, dá para tentar de novo sem recriar o cliente
      } catch (e) {
        this.erro.set(mensagemDeErro(e, 'Não foi possível cadastrar o cliente.'));
        this.enviando.set(false);
        return;
      }
    }

    // 2) Busca a usina pela SN e vincula
    try {
      const r: ResultadoVinculo = await firstValueFrom(
        this.api.vincularInversor(cliente!.id, this.form.plataforma, this.form.sn.trim()));
      this.sucesso.set({
        texto: `${cliente!.nome}: ${r.detail} (${r.inversores.length} inversor(es))`,
        usina: r.usina,
      });
      this.modo.set(null);
    } catch (e) {
      const motivo = mensagemDeErro(e, 'Não foi possível vincular a usina.');
      this.erro.set(`Cliente salvo, mas a usina não foi vinculada: ${motivo} Verifique a SN e tente de novo pelo botão "Vincular" do cliente.`);
    } finally {
      this.enviando.set(false);
      this.recarregar.update(n => n + 1);
    }
  }

  alternarAtivo(c: UsuarioCadastro): void {
    const acao = c.ativo ? 'Desativar' : 'Reativar';
    if (!confirm(`${acao} o acesso de ${c.nome}?`)) return;
    this.api.atualizar(c.id, { ativo: !c.ativo }).subscribe({
      next: () => this.recarregar.update(n => n + 1),
      error: e => alert(mensagemDeErro(e)),
    });
  }

  whatsappFormatado(numero: string | null): string {
    const d = (numero ?? '').replace(/\D/g, '');
    if (d.length === 13) return `(${d.slice(2, 4)}) ${d.slice(4, 9)}-${d.slice(9)}`;
    if (d.length === 12) return `(${d.slice(2, 4)}) ${d.slice(4, 8)}-${d.slice(8)}`;
    return numero ?? '—';
  }
}

/** Não envia campos opcionais vazios (a API trata ausente ≠ vazio). */
function limparVazios<T extends object>(dados: T): Partial<T> {
  return Object.fromEntries(Object.entries(dados).filter(([, v]) => `${v ?? ''}`.trim() !== '')) as Partial<T>;
}
