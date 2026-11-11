import { Component, computed, inject, signal } from '@angular/core';
import { toObservable, toSignal } from '@angular/core/rxjs-interop';
import { catchError, debounceTime, of, switchMap, tap } from 'rxjs';
import { LucideAngularModule, Pencil, Plus, Search } from 'lucide-angular';

import { AuthService, Perfil, ROTULO_PERFIL } from '../../services/auth.service';
import { Pagina } from '../../services/usinas.service';
import { UsuarioCadastro, UsuariosService } from '../../services/usuarios.service';
import { UsuarioFormComponent } from './usuario-form.component';

/** Usuários da equipe WL (Admin e Colaborador) — só Admin. Os clientes ficam na tela Clientes. */
@Component({
  selector: 'app-usuarios',
  imports: [LucideAngularModule, UsuarioFormComponent],
  templateUrl: './usuarios.component.html',
  styleUrl: './usuarios.component.css',
})
export class UsuariosComponent {
  private readonly api = inject(UsuariosService);
  readonly auth = inject(AuthService);

  readonly icones = { Pencil, Plus, Search };
  readonly rotuloPerfil = ROTULO_PERFIL;
  readonly perfisEquipe: Perfil[] = ['colaborador', 'admin'];

  readonly busca = signal('');
  readonly filtroPerfil = signal<Perfil | null>(null);
  private readonly recarregar = signal(0);
  readonly carregando = signal(true);

  /** null = painel fechado · 'novo' · ou o usuário em edição */
  readonly emEdicao = signal<UsuarioCadastro | 'novo' | null>(null);
  readonly sucesso = signal<string | null>(null);

  private readonly filtro = computed(() => ({
    busca: this.busca().trim(), perfil: this.filtroPerfil() ?? 'admin,colaborador', _: this.recarregar(),
  }));
  readonly resultado = toSignal(
    toObservable(this.filtro).pipe(
      debounceTime(250),
      tap(() => this.carregando.set(true)),
      switchMap(f => this.api.listar({ busca: f.busca, perfil: f.perfil }).pipe(
        catchError(() => of<Pagina<UsuarioCadastro>>({ count: 0, next: null, previous: null, results: [] })))),
      tap(() => this.carregando.set(false)),
    ),
    { initialValue: null },
  );

  usuarioEmEdicao(): UsuarioCadastro | null {
    const e = this.emEdicao();
    return e === 'novo' || e === null ? null : e;
  }

  abrirNovo(): void { this.sucesso.set(null); this.emEdicao.set('novo'); }
  abrirEdicao(u: UsuarioCadastro): void { this.sucesso.set(null); this.emEdicao.set(u); }

  aoSalvar(u: UsuarioCadastro): void {
    this.sucesso.set(`${u.nome} salvo(a) como ${this.rotuloPerfil[u.perfil]}.`);
    this.emEdicao.set(null);
    this.recarregar.update(n => n + 1);
    if (u.id === this.auth.usuario()?.id) this.auth.carregarUsuario();   // atualiza o nome no menu
  }

  ultimoAcesso(iso: string | null): string {
    return iso ? new Date(iso).toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' }) : 'nunca entrou';
  }
}
