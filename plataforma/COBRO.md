# Flujo de cobro — llm-vfx-orchestrator

## Regla
Nunca se oculta el precio para pedir el email. Los precios están publicados en plataforma/precios.json.

## Métodos de pago aceptados
- Transferencia bancaria (SEPA)
- Tarjeta de crédito/débito (vía plataforma de pago externa)
- Factura mensual para planes de soporte y gestionado

## Flujo de contratación
1. El cliente elige un plan en plataforma/OFERTA.md
2. Se emite factura con los precios de plataforma/precios.json
3. Para soporte: se configura canal prioritario y SLA
4. Para gestionado: se entrega despliegue mantenido y credenciales
5. Para consultoría: se acordan horas y se factura al finalizar

## Reembolsos
- Base: no aplica (gratuito)
- Soporte/Gestionado: reembolso proporcional si se cancela
- Consultoría: factura por horas trabajadas

