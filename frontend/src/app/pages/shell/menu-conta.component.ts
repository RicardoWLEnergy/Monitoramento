import { Component, inject, input, output, signal } from '@angular/core';
import { ChevronsUpDown, LogOut, LucideAngularModule } from 'lucide-angular';
import { AuthService, ROTULO_PERFIL } from '../../services/auth.service';

/** Bloco do usuário no rodapé da sidebar; clicar abre o menu da conta (Sair). */
@Component({
  selector: 'app-menu-conta',
  imports: [LucideAngularModule],
  templateUrl: './menu-conta.component.html',
  styleUrl: './menu-conta.component.css',
  host: {
    '[class.recolhida]': 'recolhida()',
    '(document:keydown.escape)': 'aberto.set(false)',
  },
})
export class MenuContaComponent {
  readonly auth = inject(AuthService);

  /** Sidebar recolhida: esconde nome/e-mail e abre o menu para o lado. */
  readonly recolhida = input(false);
  readonly sair = output<void>();

  readonly aberto = signal(false);
  readonly rotuloPerfil = ROTULO_PERFIL;
  readonly icones = { ChevronsUpDown, LogOut };

  aoSair(): void {
    this.aberto.set(false);
    this.sair.emit();
  }
}
