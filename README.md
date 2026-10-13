# DOCUMENTO PRONTO 📄

Bot de Telegram para criar, converter, organizar e editar documentos e arquivos. Projeto modular, com foco inicial em conversões de documentos e ferramentas de PDF.

## Estado atual
- [x] Projeto Supabase criado na região de São Paulo.
- [x] Esquema inicial do banco aplicado.
- [x] Esqueleto do bot Telegram iniciado.
- [x] Servidor webhook compatível com Render e endpoint de saúde.
- [x] Blueprint inicial de deploy em `render.yaml`.
- [ ] Renomear o repositório GitHub para `Documento-Pronto`.
- [ ] Criar o serviço no Render e configurar os segredos.
- [ ] Implementar conversores e testes funcionais.
- [ ] Configurar monitoramento e alertas.

## Funcionalidades planejadas
1. Conversões de documentos (DOCX, TXT, ODT, RTF e PDF, conforme compatibilidade).
2. Ferramentas de PDF: juntar, dividir, girar, reordenar e extrair texto.
3. Planilhas e apresentações.
4. OCR para imagens e PDFs digitalizados.
5. Edição assistida, resumo e tradução como módulos opcionais.
6. Limites Free/Premium, medição de uso e limpeza automática de arquivos temporários.

> A conversão depende do formato de origem e destino. Alguns layouts, fontes, tabelas ou recursos podem sofrer alterações. O bot deverá informar quando uma conversão não for suportada ou puder perder formatação.

## Stack inicial
- Python 3.11+
- aiogram 3
- aiohttp para o webhook do Telegram
- Supabase/PostgreSQL para metadados e uso
- LibreOffice headless, PyMuPDF/pypdf, python-docx e Pillow conforme cada conversor

## Deploy no Render
O arquivo `render.yaml` define um serviço Web gratuito e usa webhook do Telegram para que as atualizações recebidas possam acordar o serviço após suspensão. O plano gratuito pode suspender o serviço após um período sem tráfego; portanto, não há garantia de resposta instantânea ou disponibilidade contínua.

1. Abra o Render e escolha **New + → Blueprint**.
2. Conecte o repositório GitHub deste projeto e selecione `render.yaml`.
3. Informe `TELEGRAM_BOT_TOKEN` e `SUPABASE_SERVICE_ROLE_KEY` quando solicitado.
4. `SUPABASE_URL` já está definida no blueprint; `WEBHOOK_SECRET_TOKEN` será gerado pelo Render.
5. Depois do deploy, confira o endpoint `/healthz` e teste `/start` no Telegram.

Não publique nem compartilhe tokens ou chaves. A chave `service_role` deve existir somente nas variáveis privadas do ambiente do servidor.

## Desenvolvimento local
1. Instale Python 3.11 ou superior.
2. Crie e ative um ambiente virtual.
3. Instale as dependências: `pip install -r requirements.txt`.
4. Copie `.env.example` para `.env` e preencha as variáveis.
5. Para execução local com long polling, execute: `python -m bot.main`.

Nunca envie tokens, chaves privadas ou arquivos de usuários para o GitHub. Não armazene o conteúdo de arquivos no banco; guarde apenas metadados necessários e remova arquivos temporários após o prazo definido.

## Banco de dados
A primeira migração está em `supabase/migrations/20261013000000_initial_documento_pronto_schema.sql`. Ela documenta o esquema inicial já aplicado ao projeto Supabase.

## Segurança
- Validar MIME e assinatura real do arquivo, não apenas a extensão.
- Limitar tamanho, duração e frequência dos trabalhos.
- Não executar macros nem conteúdo enviado por usuários.
- Extrair arquivos compactados com proteção contra path traversal e bombas de descompactação.
- Manter RLS habilitado e acessar o banco pelo backend confiável.
- Não expor a chave `service_role` no bot distribuído, em mensagens ou no repositório.
