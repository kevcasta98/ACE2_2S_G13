# -*- coding: utf-8 -*-
"""Errores de negocio. Las rutas los convierten en JSON {"ok": false, "error": "..."}
con el código HTTP indicado, así todo rechazo lleva un mensaje explícito."""


class ErrorPortus(Exception):
    status = 400

    def __init__(self, mensaje, status=None, codigo=None):
        super().__init__(mensaje)
        self.mensaje = mensaje
        if status:
            self.status = status
        self.codigo = codigo


class NoAutenticado(ErrorPortus):
    status = 401


class ErrorPermiso(ErrorPortus):
    status = 403


class NoEncontrado(ErrorPortus):
    status = 404


class Conflicto(ErrorPortus):
    status = 409
