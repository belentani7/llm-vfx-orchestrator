# Flujo de cobro â€” llm-vfx-orchestrator

## Regla
Nunca se oculta el precio para pedir el email. Los precios estÃ¡n publicados en plataforma/precios.json.

## MÃ©todos de pago aceptados
- Transferencia bancaria (SEPA)
- Tarjeta de crÃ©dito/dÃ©bito (vÃ­a plataforma de pago externa)
- Factura mensual para planes de soporte y gestionado

## Flujo de contrataciÃ³n
1. El cliente elige un plan en plataforma/OFERTA.md
2. Se emite factura con los precios de plataforma/precios.json
3. Para soporte: se configura canal prioritario y SLA
4. Para gestionado: se entrega despliegue mantenido y credenciales
5. Para consultorÃ­a: se acordan horas y se factura al finalizar

## Reembolsos
- Base: no aplica (gratuito)
- Soporte/Gestionado: reembolso proporcional si se cancela
- ConsultorÃ­a: factura por horas trabajadas

