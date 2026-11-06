import { Component, inject, signal } from '@angular/core';
import { Router, RouterLink, RouterLinkActive, RouterOutlet, NavigationEnd } from '@angular/router';
import { filter } from 'rxjs';
import {
  Bell, Building2, FileText, LayoutDashboard, LucideAngularModule, LucideIconData,
  Menu, Moon, PanelLeftClose, PanelLeftOpen, SolarPanel, Sun, Users,
} from 'lucide-angular';
import { AuthService } from '../core/auth.service';
import { TemaService } from '../core/tema.service';
import { LogoComponent } from '../shared/logo.component';
import { MenuContaComponent } from './menu-conta.component';

interface ItemMenu { rota: string; rotulo: string; icone: LucideIconData; }

const CHAVE_RECOLHIDA = 'wl-sidebar-recolhida';

/** Estrutura das telas internas: sidebar preta (recolhível) + área de conteúdo. */
@Component({
  selector: 'app-shell',
  imports: [RouterOutlet, RouterLink, RouterLinkActive, LucideAngularModule, LogoComponent, MenuContaComponent],
  templateUrl: './shell.component.html',
  styleUrl: './shell.component.css',
  host: { '[class.recolhida]': 'recolhida()' },
})
export class ShellComponent {
  readonly auth = inject(AuthService);
  readonly tema = inject(TemaService);
  private readonly router = inject(Router);

  /** Sidebar recolhida só com ícones (desktop). Preferência salva por pessoa. */
  readonly recolhida = signal(this.lerRecolhida());
  /** Menu lateral aberto (só no mobile). */
  readonly menuAberto = signal(false);

  readonly icones = { Moon, Sun, Menu, PanelLeftClose, PanelLeftOpen };

  readonly monitoramento: ItemMenu[] = [
    { rota: '/visao-geral', rotulo: 'Visão geral', icone: LayoutDashboard },
    { rota: '/usinas',      rotulo: 'Usinas',      icone: SolarPanel },
    { rota: '/alertas',     rotulo: 'Alertas',     icone: Bell },
    { rota: '/relatorios',  rotulo: 'Relatórios',  icone: FileText },
  ];

  readonly administracao: ItemMenu[] = [
    { rota: '/clientes', rotulo: 'Clientes', icone: Building2 },
    { rota: '/usuarios', rotulo: 'Usuários', icone: Users },
  ];

  constructor() {
    // Fecha o menu mobile ao navegar
    this.router.events
      .pipe(filter(e => e instanceof NavigationEnd))
      .subscribe(() => this.menuAberto.set(false));
  }

  alternarSidebar(): void {
    const valor = !this.recolhida();
    this.recolhida.set(valor);
    try { localStorage.setItem(CHAVE_RECOLHIDA, valor ? '1' : '0'); } catch { /* ignora */ }
  }

  sair(): void {
    this.auth.sair();
    this.router.navigateByUrl('/login');
  }

  private lerRecolhida(): boolean {
    try { return localStorage.getItem(CHAVE_RECOLHIDA) === '1'; } catch { return false; }
  }
}
