import { inject } from '@angular/core';
import { CanActivateFn, Router, UrlTree } from '@angular/router';
import { catchError, map, Observable, of } from 'rxjs';
import { AuthService } from './auth.service';
import { UsinasService } from './usinas.service';

/**
 * Tela inicial conforme o perfil:
 * - Admin e Colaborador → Visão geral (painel da carteira)
 * - Cliente → direto na usina dele; se tiver mais de uma, na lista de Usinas
 */
export const inicioGuard: CanActivateFn = (): UrlTree | Observable<UrlTree> => {
  const auth = inject(AuthService);
  const router = inject(Router);
  if (auth.eEquipe()) return router.createUrlTree(['/visao-geral']);
  return inject(UsinasService).listar({ page: 1 }).pipe(
    map(r => r.count === 1 ? router.createUrlTree(['/usinas', r.results[0].id]) : router.createUrlTree(['/usinas'])),
    catchError(() => of(router.createUrlTree(['/usinas']))),
  );
};

/** Bloqueia rotas internas para quem não está logado. */
export const authGuard: CanActivateFn = () => {
  const auth = inject(AuthService);
  return auth.logado() ? true : inject(Router).createUrlTree(['/login']);
};

/** Impede voltar ao login quem já está logado. */
export const visitanteGuard: CanActivateFn = () => {
  const auth = inject(AuthService);
  return auth.logado() ? inject(Router).createUrlTree(['/']) : true;
};

/** Só Admin e Colaborador (ex.: cadastro de clientes). */
export const equipeGuard: CanActivateFn = () => {
  const auth = inject(AuthService);
  return auth.eEquipe() ? true : inject(Router).createUrlTree(['/']);
};

/** Só Admin. */
export const adminGuard: CanActivateFn = () => {
  const auth = inject(AuthService);
  return auth.eAdmin() ? true : inject(Router).createUrlTree(['/']);
};
