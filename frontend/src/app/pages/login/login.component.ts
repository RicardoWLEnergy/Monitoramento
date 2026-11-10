import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { ArrowRight, Lock, LucideAngularModule, Mail } from 'lucide-angular';
import { AuthService } from '../../services/auth.service';
import { LogoComponent } from '../shell/logo.component';

/** Login — sempre escuro, sem sidebar, card centralizado. */
@Component({
  selector: 'app-login',
  imports: [FormsModule, LucideAngularModule, LogoComponent],
  templateUrl: './login.component.html',
  styleUrl: './login.component.css',
})
export class LoginComponent {
  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);

  readonly icones = { ArrowRight, Lock, Mail };

  email = '';
  senha = '';
  readonly carregando = signal(false);
  readonly erro = signal<string | null>(null);

  async entrar(): Promise<void> {
    this.erro.set(null);
    this.carregando.set(true);
    try {
      await this.auth.entrar(this.email, this.senha);
      await this.router.navigateByUrl('/');
    } catch (e) {
      this.erro.set(e instanceof Error ? e.message : 'Não foi possível entrar.');
    } finally {
      this.carregando.set(false);
    }
  }
}
