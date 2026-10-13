# DOCUMENTO PRONTO 📄

Bot de Telegram para criar, converter e organizar documentos. O projeto usa Python, aiogram, Supabase, PyMuPDF, pypdf, openpyxl, python-pptx, pdfplumber, Tesseract OCR e LibreOffice.

## Funcionalidades

- Criar documentos Word e PDF a partir de texto.
- Converter PDF em TXT, Word, Excel, PowerPoint ou JPG.
- Converter TXT e imagens para PDF/Word quando compatível.
- Converter Excel (.xlsx) e PowerPoint (.pptx) para PDF.
- Juntar PDFs, dividir páginas e extrair texto selecionável.
- Aplicar OCR em PDFs digitalizados e produzir PDF pesquisável.
- Otimizar PDFs e reordenar, girar ou remover páginas.
- Consultar cota diária com /uso.

## Observações

- PDF para Excel depende de texto e tabelas detectáveis. PDF digitalizado deve passar pelo OCR antes da extração.
- PDF para PowerPoint cria um slide por página como imagem. O visual é preservado, mas texto e elementos não ficam editáveis.
- Excel/PowerPoint para PDF dependem do LibreOffice e das fontes disponíveis; layouts complexos podem mudar.
- OCR aceita até 30 páginas por operação; PDF para JPG e PDF para PowerPoint aceitam até 100 páginas.
- Arquivos são processados com buffers e arquivos temporários; não publique documentos de usuários no repositório.

## Deploy no Render

O runtime Docker instala LibreOffice, Tesseract OCR com idiomas português/inglês e as dependências Python. Configure TELEGRAM_BOT_TOKEN e SUPABASE_SERVICE_ROLE_KEY como segredos no Render. Confira o endpoint /healthz após o deploy.

Se o Blueprint atual ainda estiver configurado como Python nativo, sincronize as alterações de render.yaml e confirme que o runtime do serviço foi alterado para Docker antes de validar OCR e conversões Office. O plano gratuito do Render pode suspender o serviço após inatividade, sem garantia de resposta instantânea ou disponibilidade contínua.

## Desenvolvimento local

Instale Python 3.11+, as dependências de requirements.txt, LibreOffice e Tesseract com idiomas português e inglês. Configure as variáveis de ambiente e execute o módulo bot.main para long polling ou bot.web para webhook.

Não publique tokens, chaves privadas ou arquivos pessoais no GitHub.
