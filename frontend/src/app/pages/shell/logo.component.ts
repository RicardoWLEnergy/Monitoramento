import { Component, computed, inject, input } from '@angular/core';
import { TemaService } from '../../services/tema.service';

/**
 * Logo W.L Energy.
 *  - fundo="tema"   → segue o tema: escuro = ENERGYWL (branco), claro = ENERGY_BLACKWL (preto)
 *  - fundo="escuro" → superfícies SEMPRE pretas (sidebar, topo mobile, login): usa sempre o branco
 */
@Component({
  selector: 'app-logo',
  template: `<img [src]="arquivo()" alt="W.L Energy" [style.height.px]="altura()">`,
  styles: `:host { display: inline-flex; } img { display: block; width: auto; }`,
})
export class LogoComponent {
  private readonly tema = inject(TemaService);

  readonly fundo = input<'tema' | 'escuro'>('tema');
  readonly altura = input(28);

  readonly arquivo = computed(() => {
    const escuro = this.fundo() === 'escuro' || this.tema.tema() === 'escuro';
    return escuro ? 'ENERGYWL.png' : 'ENERGY_BLACKWL.png';
  });
}
