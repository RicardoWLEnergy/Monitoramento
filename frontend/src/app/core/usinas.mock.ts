/**
 * Dados SIMULADOS para desenvolver as telas sem backend.
 * Os tipos abaixo servirão de contrato para a futura API Django.
 */

export type Fabricante = 'WEG' | 'FoxESS' | 'Huawei';
export type StatusUsina = 'online' | 'alerta' | 'offline';

export interface Usina {
  id: number;
  nome: string;
  cliente: string;
  cidade: string;
  fabricante: Fabricante;
  potenciaKwp: number;
  potenciaAtualKw: number;
  geracaoHojeKwh: number;
  geracaoMesKwh: number;
  esperadoMesKwh: number;
  status: StatusUsina;
  ultimaLeitura: string; // ISO
}

const agora = new Date();
const minutosAtras = (m: number) => new Date(agora.getTime() - m * 60_000).toISOString();

export const USINAS_MOCK: Usina[] = [
  { id: 1,  nome: 'Residencial Lago Sul',      cliente: 'Marcos Andrade',          cidade: 'Brasília - DF',   fabricante: 'Huawei', potenciaKwp: 12.3,  potenciaAtualKw: 8.4,   geracaoHojeKwh: 41.2,   geracaoMesKwh: 248.6,   esperadoMesKwh: 260,   status: 'online',  ultimaLeitura: minutosAtras(4) },
  { id: 2,  nome: 'Supermercado Bom Preço',     cliente: 'Bom Preço Ltda',          cidade: 'Taguatinga - DF', fabricante: 'WEG',    potenciaKwp: 65.28, potenciaAtualKw: 44.1,  geracaoHojeKwh: 212.5,  geracaoMesKwh: 1288.4,  esperadoMesKwh: 1350,  status: 'online',  ultimaLeitura: minutosAtras(6) },
  { id: 3,  nome: 'Clínica Vida',               cliente: 'Clínica Vida S/S',        cidade: 'Águas Claras - DF', fabricante: 'FoxESS', potenciaKwp: 30.6,  potenciaAtualKw: 9.7,   geracaoHojeKwh: 58.3,   geracaoMesKwh: 472.0,   esperadoMesKwh: 640,   status: 'alerta',  ultimaLeitura: minutosAtras(9) },
  { id: 4,  nome: 'Fazenda Santa Rita',         cliente: 'Agropecuária Santa Rita', cidade: 'Formosa - GO',    fabricante: 'WEG',    potenciaKwp: 112.2, potenciaAtualKw: 0,     geracaoHojeKwh: 96.8,   geracaoMesKwh: 1920.3,  esperadoMesKwh: 2350,  status: 'offline', ultimaLeitura: minutosAtras(185) },
  { id: 5,  nome: 'Residencial Park Way',       cliente: 'Juliana Costa',           cidade: 'Brasília - DF',   fabricante: 'FoxESS', potenciaKwp: 8.16,  potenciaAtualKw: 5.9,   geracaoHojeKwh: 27.4,   geracaoMesKwh: 168.9,   esperadoMesKwh: 172,   status: 'online',  ultimaLeitura: minutosAtras(3) },
  { id: 6,  nome: 'Posto Avenida',              cliente: 'Auto Posto Avenida',      cidade: 'Gama - DF',       fabricante: 'Huawei', potenciaKwp: 45.9,  potenciaAtualKw: 31.2,  geracaoHojeKwh: 148.1,  geracaoMesKwh: 905.7,   esperadoMesKwh: 950,   status: 'online',  ultimaLeitura: minutosAtras(5) },
  { id: 7,  nome: 'Escola Saber',               cliente: 'Instituto Saber',         cidade: 'Sobradinho - DF', fabricante: 'Huawei', potenciaKwp: 75.0,  potenciaAtualKw: 22.6,  geracaoHojeKwh: 160.4,  geracaoMesKwh: 1302.2,  esperadoMesKwh: 1560,  status: 'alerta',  ultimaLeitura: minutosAtras(7) },
  { id: 8,  nome: 'Residencial Jardim Botânico', cliente: 'Paulo Henrique Lima',    cidade: 'Brasília - DF',   fabricante: 'WEG',    potenciaKwp: 10.2,  potenciaAtualKw: 7.1,   geracaoHojeKwh: 33.9,   geracaoMesKwh: 207.5,   esperadoMesKwh: 215,   status: 'online',  ultimaLeitura: minutosAtras(2) },
  { id: 9,  nome: 'Galpão Logística Norte',     cliente: 'LogNorte Transportes',    cidade: 'Sobradinho - DF', fabricante: 'FoxESS', potenciaKwp: 98.4,  potenciaAtualKw: 70.3,  geracaoHojeKwh: 331.0,  geracaoMesKwh: 2011.8,  esperadoMesKwh: 2050,  status: 'online',  ultimaLeitura: minutosAtras(4) },
  { id: 10, nome: 'Padaria Pão Dourado',        cliente: 'Pão Dourado ME',          cidade: 'Ceilândia - DF',  fabricante: 'WEG',    potenciaKwp: 18.36, potenciaAtualKw: 0,     geracaoHojeKwh: 0,      geracaoMesKwh: 301.2,   esperadoMesKwh: 380,   status: 'offline', ultimaLeitura: minutosAtras(1440) },
  { id: 11, nome: 'Residencial Sudoeste',       cliente: 'Fernanda Rocha',          cidade: 'Brasília - DF',   fabricante: 'Huawei', potenciaKwp: 6.12,  potenciaAtualKw: 4.3,   geracaoHojeKwh: 20.8,   geracaoMesKwh: 126.4,   esperadoMesKwh: 129,   status: 'online',  ultimaLeitura: minutosAtras(3) },
  { id: 12, nome: 'Academia Força Total',       cliente: 'Força Total Fitness',     cidade: 'Guará - DF',      fabricante: 'FoxESS', potenciaKwp: 24.48, potenciaAtualKw: 17.0,  geracaoHojeKwh: 79.6,   geracaoMesKwh: 489.0,   esperadoMesKwh: 505,   status: 'online',  ultimaLeitura: minutosAtras(8) },
];
