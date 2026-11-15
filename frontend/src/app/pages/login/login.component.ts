import { Component, DestroyRef, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { ArrowRight, KeyRound, Lock, LucideAngularModule, Mail, MessageCircle } from 'lucide-angular';
import { AuthService, CodigoEnviado } from '../../services/auth.service';
import { LogoComponent } from '../shell/logo.component';

/**
 * Login — sempre escuro, sem sidebar, card centralizado.
 * Duas formas: e-mail + senha, ou e-mail + código enviado ao WhatsApp cadastrado.
 */
@Component({
  selector: 'app-login',
  imports: [FormsModule, LucideAngularModule, LogoComponent],
  templateUrl: './login.component.html',
  styleUrl: './login.component.css',
})
export class LoginComponent {
  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);

  readonly icones = { ArrowRight, KeyRound, Lock, Mail, MessageCircle };

  email = '';
  senha = '';
  codigo = '';
  readonly modo = signal<'senha' | 'codigo'>('senha');
  readonly enviado = signal<CodigoEnviado | null>(null);
  /** Segundos até poder pedir outro código. */
  readonly espera = signal(0);
  readonly carregando = signal(false);
  readonly erro = signal<string | null>(null);

  private contador: ReturnType<typeof setInterval> | null = null;

  constructor() {
    inject(DestroyRef).onDestroy(() => this.pararContador());
  }

  trocarModo(modo: 'senha' | 'codigo'): void {
    this.modo.set(modo);
    this.erro.set(null);
    this.enviado.set(null);
    this.codigo = '';
  }

  /** Botão principal: entrar com senha, enviar o código ou entrar com o código. */
  async confirmar(): Promise<void> {
    if (this.modo() === 'codigo' && !this.enviado()) return this.enviarCodigo();
    await this.executar(async () => {
      if (this.modo() === 'senha') await this.auth.entrar(this.email, this.senha);
      else await this.auth.entrarComCodigo(this.email, this.codigo);
      await this.router.navigateByUrl('/');
    });
  }

  async enviarCodigo(): Promise<void> {
    await this.executar(async () => {
      const r = await this.auth.pedirCodigo(this.email);
      this.enviado.set(r);
      this.codigo = '';
      this.iniciarContador(r.reenvio_segundos);
    });
  }

  /** Mudou o e-mail depois de enviar: volta para "Enviar código". */
  emailAlterado(): void {
    if (this.enviado()) this.enviado.set(null);
  }

  private async executar(acao: () => Promise<void>): Promise<void> {
    this.erro.set(null);
    this.carregando.set(true);
    try {
      await acao();
    } catch (e) {
      this.erro.set(e instanceof Error ? e.message : 'Não foi possível entrar.');
    } finally {
      this.carregando.set(false);
    }
  }

  private iniciarContador(segundos: number): void {
    this.pararContador();
    this.espera.set(segundos);
    this.contador = setInterval(() => {
      this.espera.update(s => s - 1);
      if (this.espera() <= 0) this.pararContador();
    }, 1000);
  }

  private pararContador(): void {
    if (this.contador) clearInterval(this.contador);
    this.contador = null;
  }
}
