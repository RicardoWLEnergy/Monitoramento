import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpParams, HttpResponse } from '@angular/common/http';
import { Observable, map } from 'rxjs';

export type StatusEtapa = 'concluida' | 'andamento' | 'proxima';
export type ChaveEtapa = 'onboarding' | 'homologacao' | 'projeto_executivo' | 'instalacao' | 'comissionamento';

/** Documento de uma etapa (arquivo no Drive; o servidor entrega só ao dono). */
export interface DocumentoProjeto {
  tipo: string;
  nome: string;
  disponivel: boolean;
  /** Quando ainda não está disponível (ex.: "Disponível ao fim da instalação"). */
  aviso: string;
}

export interface EtapaProjeto {
  chave: ChaveEtapa;
  nome: string;
  status: StatusEtapa;
  inicio: string | null;            // AAAA-MM-DD (realizado)
  fim: string | null;               // AAAA-MM-DD (realizado)
  previsao_inicio: string | null;
  previsao_fim: string | null;
  documentos: DocumentoProjeto[];
  /** Comissionamento e vistoria: prazo da concessionária para a vistoria. */
  prazo_vistoria?: string | null;
}

/** Projeto de instalação do cliente (uma linha da planilha OBRAS, achada pelo ID do cliente). */
export interface Projeto {
  id_cliente: string;
  potencia_kwp: number | null;
  modulos: number | null;
  cidade: string;
  uf: string;
  /** Prazo da vistoria quando já pedida; antes disso, null (prazos das etapas ainda a definir). */
  previsao_conclusao: string | null;
  etapas: EtapaProjeto[];
}

/**
 * O que acontece em cada etapa, no tempo verbal da situação dela:
 * feito (concluída) · agora (em andamento) · depois (próxima).
 */
export const TEXTOS_ETAPA: Record<ChaveEtapa, Record<'feito' | 'agora' | 'depois', string[]>> = {
  onboarding: {
    feito: ['Conferimos seus dados e a conta de energia.', 'Confirmamos o local onde a usina será instalada.'],
    agora: ['Estamos conferindo seus dados e a conta de energia.', 'Vamos confirmar o local onde a usina será instalada.'],
    depois: ['Vamos conferir seus dados e a conta de energia.', 'Vamos confirmar o local onde a usina será instalada.'],
  },
  homologacao: {
    feito: ['Registramos a ART do projeto.', 'Enviamos o projeto à concessionária.',
      'A concessionária aprovou a conexão da sua usina à rede (Parecer de Acesso).'],
    agora: ['Registramos a ART e enviamos o projeto à concessionária.',
      'Estamos aguardando a aprovação da concessionária (Parecer de Acesso).'],
    depois: ['Vamos registrar a ART do projeto.', 'Vamos enviar o projeto à concessionária e aguardar a aprovação (Parecer de Acesso).'],
  },
  projeto_executivo: {
    feito: ['Definimos a posição de cada módulo.', 'Desenhamos o caminho dos cabos e as proteções elétricas.',
      'A prancha do projeto está disponível nos documentos.'],
    agora: ['Estamos definindo a posição de cada módulo.', 'Desenhamos o caminho dos cabos e as proteções elétricas.',
      'Ao terminar, a prancha do projeto fica disponível aqui.'],
    depois: ['Vamos definir a posição de cada módulo.', 'Vamos desenhar o caminho dos cabos e as proteções elétricas.'],
  },
  instalacao: {
    feito: ['Montamos a estrutura, os módulos e o inversor.', 'Fizemos as ligações elétricas e os primeiros testes (comissionamento nível 01).'],
    agora: ['Nossa equipe está montando a estrutura, os módulos e o inversor.', 'Depois, fazemos as ligações elétricas e os primeiros testes.'],
    depois: ['Nossa equipe vai montar a estrutura, os módulos e o inversor.',
      'Vamos fazer as ligações elétricas e os primeiros testes (comissionamento nível 01).'],
  },
  comissionamento: {
    feito: ['Testamos a usina completa (comissionamento nível 02).', 'A concessionária fez a vistoria.', 'Sua usina está liberada para gerar.'],
    agora: ['Testamos a usina completa (comissionamento nível 02).', 'Estamos aguardando a vistoria da concessionária.',
      'Depois da vistoria, a usina é liberada para gerar.'],
    depois: ['Vamos testar a usina completa (comissionamento nível 02).', 'Vamos pedir a vistoria à concessionária.',
      'Depois da vistoria, a usina é liberada para gerar.'],
  },
};

/** Acompanhamento do projeto de instalação (tela "Meu projeto"). */
@Injectable({ providedIn: 'root' })
export class ProjetoService {
  private readonly http = inject(HttpClient);

  /** Projeto do cliente logado. A equipe pode consultar o de um cliente pelo ID (idCliente). */
  meuProjeto(idCliente?: string | null): Observable<Projeto | null> {
    const params = idCliente ? new HttpParams().set('id_cliente', idCliente) : undefined;
    return this.http.get<{ projeto: Projeto | null }>('/api/projeto/', { params }).pipe(map(r => r.projeto));
  }

  /** Baixa um documento (o servidor confere se é do cliente) e salva no computador. */
  baixar(tipo: string, idCliente?: string | null): Observable<void> {
    const params = idCliente ? new HttpParams().set('id_cliente', idCliente) : undefined;
    return this.http.get(`/api/projeto/documentos/${tipo}/`, { params, responseType: 'blob', observe: 'response' })
      .pipe(map(r => salvarArquivo(r, `${tipo}.pdf`)));
  }
}

/** O erro de um download chega como arquivo (Blob): lê a mensagem do servidor ("ainda não está disponível" etc.). */
export async function mensagemDoDownload(erro: unknown): Promise<string> {
  const corpo = (erro as { error?: unknown })?.error;
  if (corpo instanceof Blob) {
    try { return JSON.parse(await corpo.text()).detail ?? 'Não foi possível baixar o documento.'; } catch { /* segue */ }
  }
  return 'Não foi possível baixar o documento.';
}

function salvarArquivo(resposta: HttpResponse<Blob>, padrao: string): void {
  const cabecalho = resposta.headers.get('Content-Disposition') ?? '';
  const nome = decodeURIComponent(/filename\*=UTF-8''([^;]+)/.exec(cabecalho)?.[1] ?? padrao);
  const url = URL.createObjectURL(resposta.body!);
  const link = Object.assign(document.createElement('a'), { href: url, download: nome });
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
