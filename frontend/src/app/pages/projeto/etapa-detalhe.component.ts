import { Component, computed, inject, input, output, signal } from '@angular/core';
import { Check, CircleDashed, Clock, Download, FileText, LucideAngularModule, SquareCheck } from 'lucide-angular';

import { dataBR, diasEntre, hojeIso } from '../../services/periodo';
import { mensagemDeErro } from '../../services/auth.service';
import { DocumentoProjeto, EtapaProjeto, ProjetoService, StatusEtapa, TEXTOS_ETAPA } from '../../services/projeto.service';

const TITULO: Record<StatusEtapa, string> = {
  concluida: 'O que foi feito', andamento: 'O que está acontecendo agora', proxima: 'O que vai acontecer',
};
const ROTULO: Record<StatusEtapa, string> = { concluida: 'Concluída', andamento: 'Em andamento', proxima: 'Próxima' };
const CLASSE: Record<StatusEtapa, string> = { concluida: 'ok', andamento: 'warn', proxima: 'neutral' };
const plural = (n: number, um: string, varios: string) => `${n} ${n === 1 ? um : varios}`;

/** Painel de uma etapa do projeto: o que foi feito / está acontecendo / vai acontecer, datas e documentos. */
@Component({
  selector: 'app-etapa-detalhe',
  imports: [LucideAngularModule],
  templateUrl: './etapa-detalhe.component.html',
  styleUrl: './etapa-detalhe.component.css',
})
export class EtapaDetalheComponent {
  readonly etapa = input.required<EtapaProjeto>();
  readonly indice = input.required<number>();
  readonly total = input.required<number>();
  /** No celular o painel abre dentro da lista: sem cabeçalho nem navegação. */
  readonly compacto = input(false);
  /** Equipe consultando o projeto de um cliente: o ID dele (o cliente usa o próprio). */
  readonly idCliente = input<string | null>(null);
  readonly ir = output<number>();

  private readonly api = inject(ProjetoService);
  readonly baixando = signal<string | null>(null);
  readonly erroDownload = signal<string | null>(null);

  readonly icones = { Check, Download, FileText };
  readonly titulo = computed(() => TITULO[this.etapa().status]);
  readonly rotulo = computed(() => ROTULO[this.etapa().status]);
  readonly classe = computed(() => CLASSE[this.etapa().status]);
  readonly iconeItem = computed(() =>
    ({ concluida: SquareCheck, andamento: Clock, proxima: CircleDashed })[this.etapa().status]);

  readonly itens = computed(() => {
    const e = this.etapa();
    const vez = e.status === 'concluida' ? 'feito' : e.status === 'andamento' ? 'agora' : 'depois';
    return TEXTOS_ETAPA[e.chave][vez];
  });

  /** Datas conforme a situação: realizadas + duração; início + quanto falta; ou só as previsões. */
  readonly datas = computed(() => {
    const e = this.etapa();
    const d = (iso: string | null | undefined) => (iso ? dataBR(iso) : 'a definir');
    if (e.status === 'concluida') {
      const linhas = [['Início', d(e.inicio)], ['Conclusão', d(e.fim)]];
      if (e.inicio && e.fim) linhas.push(['Duração', plural(Math.max(1, diasEntre(e.inicio, e.fim)), 'dia', 'dias')]);
      return linhas;
    }
    if (e.status === 'andamento') {
      const linhas = [['Início', d(e.inicio)], ['Previsão de conclusão', d(e.previsao_fim)]];
      if (e.previsao_fim) {
        const faltam = diasEntre(hojeIso(), e.previsao_fim);
        linhas.push(['Faltam', faltam > 0 ? plural(faltam, 'dia', 'dias') : faltam === 0 ? 'termina hoje' : 'prazo em revisão']);
      }
      return linhas;
    }
    return [['Previsão de início', d(e.previsao_inicio)], ['Previsão de conclusão', d(e.previsao_fim)]];
  });

  readonly vistoria = computed(() => {
    const prazo = this.etapa().prazo_vistoria;
    return prazo ? dataBR(prazo) : null;
  });

  baixar(d: DocumentoProjeto): void {
    this.baixando.set(d.tipo);
    this.erroDownload.set(null);
    this.api.baixar(d.tipo, this.idCliente()).subscribe({
      next: () => this.baixando.set(null),
      error: e => { this.baixando.set(null); this.erroDownload.set(mensagemDeErro(e, 'Não foi possível baixar o documento.')); },
    });
  }
}
