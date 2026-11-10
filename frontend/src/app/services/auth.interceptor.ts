import { HttpErrorResponse, HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { Router } from '@angular/router';
import { catchError, switchMap, throwError } from 'rxjs';
import { AuthService } from './auth.service';

const SEM_TOKEN = ['/api/auth/login/', '/api/auth/renovar/'];

/**
 * Coloca o token em toda chamada à API. Se a API responder 401 (token vencido),
 * renova o token uma vez e repete a chamada; se não der, volta para o login.
 */
export const authInterceptor: HttpInterceptorFn = (req, next) => {
  if (!req.url.startsWith('/api/') || SEM_TOKEN.some(u => req.url.startsWith(u))) {
    return next(req);
  }
  const auth = inject(AuthService);
  const router = inject(Router);
  const comToken = (token: string | null) =>
    token ? req.clone({ setHeaders: { Authorization: `Bearer ${token}` } }) : req;

  return next(comToken(auth.tokenAcesso())).pipe(
    catchError((erro: HttpErrorResponse) => {
      if (erro.status !== 401 || !auth.tokenRenovacao()) return throwError(() => erro);
      return auth.renovar().pipe(
        switchMap(novo => next(comToken(novo))),
        catchError(falha => {
          auth.sair();
          router.navigateByUrl('/login');
          return throwError(() => falha);
        }),
      );
    }),
  );
};
