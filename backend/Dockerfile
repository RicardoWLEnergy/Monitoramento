# Receita da imagem do backend (usada pela API e pelo coletor)
FROM python:3.11-slim

# Não grava arquivos .pyc e mostra os registros na hora (importante para o "docker compose logs")
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Pacotes ANTES do código: se só o código mudar, o Docker reaproveita esta etapa (build mais rápido)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Junta os arquivos visuais do /admin (valores falsos só para esta etapa rodar)
RUN DJANGO_SECRET_KEY=chave-falsa-usada-so-para-juntar-os-arquivos-do-build DATABASE_URL=sqlite:////tmp/build.db \
    python manage.py collectstatic --noinput

# Segurança: o sistema roda com um usuário comum, não como administrador do contêiner
RUN useradd --create-home app && chown -R app /app
USER app

EXPOSE 8000

# Gunicorn: 3 atendentes (ideal para 1 núcleo) e tempo-limite de 2 min
# (a importação de histórico roda no coletor, não na requisição; o cadastro por SN consulta a plataforma)
CMD ["gunicorn", "backend.wsgi:application", "--bind", "0.0.0.0:8000", \
     "--workers", "3", "--timeout", "120", "--access-logfile", "-"]
