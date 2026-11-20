import { HttpErrorResponse, HttpInterceptorFn } from '@angular/common/http';
import { catchError, throwError } from 'rxjs';

/**
 * Sistema em manutenção (API reiniciando/atualizando, ou modo manutenção ligado no servidor):
 * o Caddy responde {"manutencao": true}. Nesse caso abre a página de manutenção, que volta
 * sozinha para esta tela quando o sistema responder. Outros erros (ex.: "planilha indisponível")
 * não têm essa marca e seguem para a tela tratar.
 */
export const manutencaoInterceptor: HttpInterceptorFn = (req, next) =>
  next(req).pipe(
    catchError((erro: HttpErrorResponse) => {
      if (req.url.startsWith('/api/') && erro.error?.manutencao === true) {
        const voltar = encodeURIComponent(location.pathname + location.search);
        location.assign(`/manutencao.html?voltar=${voltar}`);
      }
      return throwError(() => erro);
    }),
  );
