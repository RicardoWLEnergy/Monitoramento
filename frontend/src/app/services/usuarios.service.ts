import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import { Perfil } from './auth.service';
import { Pagina, Plataforma } from './usinas.service';

export interface UsuarioCadastro {
  id: number;
  email: string;
  nome: string;
  whatsapp: string | null;
  cpf: string | null;
  cpf_formatado: string;
  endereco: string;
  latitude: number | null;
  longitude: number | null;
  link_maps: string | null;
  perfil: Perfil;
  ativo: boolean;
  criado_em: string;
  last_login: string | null;
  usinas: { id: number; nome: string }[];
}

export interface NovoUsuario {
  email: string;
  nome: string;
  whatsapp?: string;
  cpf?: string;
  endereco?: string;
  perfil?: Perfil;
  senha?: string;
}

export interface ResultadoVinculo {
  detail: string;
  usina: { id: number; nome: string };
  usina_nova: boolean;
  inversores: string[];
}

/** Chamadas à API de usuários (/api/usuarios/) — Admin e Colaborador. */
@Injectable({ providedIn: 'root' })
export class UsuariosService {
  private readonly http = inject(HttpClient);

  /** `perfil` aceita um ou vários separados por vírgula (ex.: 'admin,colaborador'). */
  listar(filtro: { busca?: string; perfil?: Perfil | string; page?: number }): Observable<Pagina<UsuarioCadastro>> {
    let params = new HttpParams();
    for (const [chave, valor] of Object.entries(filtro)) {
      if (valor) params = params.set(chave, String(valor));
    }
    return this.http.get<Pagina<UsuarioCadastro>>('/api/usuarios/', { params });
  }

  criar(dados: NovoUsuario): Observable<UsuarioCadastro> {
    return this.http.post<UsuarioCadastro>('/api/usuarios/', dados);
  }

  atualizar(id: number, dados: Partial<NovoUsuario> & { ativo?: boolean }): Observable<UsuarioCadastro> {
    return this.http.patch<UsuarioCadastro>(`/api/usuarios/${id}/`, dados);
  }

  /** Busca a usina do inversor (SN) na plataforma, grava e vincula ao cliente. */
  vincularInversor(id: number, plataforma: Plataforma, sn: string): Observable<ResultadoVinculo> {
    return this.http.post<ResultadoVinculo>(`/api/usuarios/${id}/vincular-inversor/`, { plataforma, sn });
  }
}
