# DOCUMENTO PRONTO 📄

Bot de Telegram para criar, converter, organizar e editar documentos e arquivos. Projeto modular, com foco inicial em conversões de documentos e ferramentas de PDF.

## Estado atual
- [x] Projeto Supabase criado na região de São Paulo.
- [x] Esquema inicial do banco aplicado.
- [x] Esqueleto do bot Telegram iniciado.
- [ ] Configurar token do Telegram no ambiente de execução.
- [ ] Conectar camada de dados ao Supabase.
- [ ] Implementar conversores e testes.
- [ ] Configurar deploy e monitoramento.

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
- Supabase/PostgreSQL para metadados e uso
- LibreOffice headless, PyMuPDF/pypdf, python-docx e Pillow conforme cada conversor

## Desenvolvimento local
1. Instale Python 3.11 ou superior.
2. Crie e ative um ambiente virtual.
3. Instale as dependências: `pip install -r requirements.txt`.
4. Copie `.env.example` para `.env` e preencha as variáveis.
5. Execute: `python -m bot.main`.

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
