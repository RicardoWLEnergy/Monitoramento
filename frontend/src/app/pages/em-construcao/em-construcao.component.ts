import { Component, inject } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { Construction, LucideAngularModule } from 'lucide-angular';

/** Placeholder para telas ainda não implementadas. */
@Component({
  selector: 'app-em-construcao',
  imports: [RouterLink, LucideAngularModule],
  template: `
    <div class="eyebrow">Em breve</div>
    <h1>{{ titulo }}</h1>
    <div class="vazio" style="margin-top: 24px">
      <lucide-icon [img]="icone" [size]="28" [strokeWidth]="1.5" style="margin-bottom: 10px" /><br>
      Esta tela ainda está em desenvolvimento.<br>
      <a routerLink="/visao-geral">Voltar para a visão geral →</a>
    </div>
  `,
})
export class EmConstrucaoComponent {
  readonly icone = Construction;
  readonly titulo: string = inject(ActivatedRoute).snapshot.data['titulo'] ?? 'Em construção';
}
