import { Component, OnChanges, inject, input, output, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { LucideAngularModule, X } from 'lucide-angular';

import { AuthService, Perfil, ROTULO_PERFIL, mensagemDeErro } from '../../services/auth.service';
import { NovoUsuario, UsuarioCadastro, UsuariosService } from '../../services/usuarios.service';

interface Formulario {
  nome: string; email: string; cpf: string; whatsapp: string; endereco: string;
  perfil: Perfil; senha: string; ativo: boolean;
}

/**
 * Formulário de usuário — criar ou editar.
 * Usado em Clientes (editar cliente) e em Usuários (criar/editar colaborador ou admin).
 */
@Component({
  selector: 'app-usuario-form',
  imports: [FormsModule, LucideAngularModule],
  templateUrl: './usuario-form.component.html',
  styleUrl: './usuario-form.component.css',
})
export class UsuarioFormComponent implements OnChanges {
  private readonly api = inject(UsuariosService);
  readonly auth = inject(AuthService);

  /** null = novo usuário. */
  readonly usuario = input<UsuarioCadastro | null>(null);
  /** Perfis que podem ser escolhidos (o primeiro é o padrão de um novo usuário). */
  readonly perfis = input<Perfil[]>(['cliente']);
  readonly titulo = input('');

  readonly salvo = output<UsuarioCadastro>();
  readonly cancelar = output<void>();

  readonly icones = { X };
  readonly rotuloPerfil = ROTULO_PERFIL;
  form!: Formulario;
  readonly enviando = signal(false);
  readonly erro = signal<string | null>(null);

  get editando(): boolean { return this.usuario() !== null; }
  /** Não deixa o próprio usuário se desativar ou mudar o próprio perfil (a API também bloqueia). */
  get eVoceMesmo(): boolean { return this.usuario()?.id === this.auth.usuario()?.id; }

  ngOnChanges(): void {
    const u = this.usuario();
    this.form = {
      nome: u?.nome ?? '', email: u?.email ?? '', cpf: u?.cpf_formatado ?? '',
      whatsapp: u?.whatsapp ?? '', endereco: u?.endereco ?? '',
      perfil: u?.perfil ?? this.perfis()[0], senha: '', ativo: u?.ativo ?? true,
    };
    this.erro.set(null);
  }

  enviar(): void {
    this.enviando.set(true);
    this.erro.set(null);
    const f = this.form;
    const dados: NovoUsuario & { ativo?: boolean } = {
      nome: f.nome.trim(), email: f.email.trim(), cpf: f.cpf.trim(), whatsapp: f.whatsapp.trim(),
      endereco: f.endereco.trim(),
    };
    if (this.perfis().length > 1 && !this.eVoceMesmo) dados.perfil = f.perfil;
    if (!this.editando) dados.perfil = f.perfil;
    if (f.senha) dados.senha = f.senha;
    if (this.editando && !this.eVoceMesmo) dados.ativo = f.ativo;

    const u = this.usuario();
    const chamada = u ? this.api.atualizar(u.id, dados) : this.api.criar(dados);
    chamada.subscribe({
      next: r => { this.enviando.set(false); this.salvo.emit(r); },
      error: e => { this.enviando.set(false); this.erro.set(mensagemDeErro(e, 'Não foi possível salvar.')); },
    });
  }
}
