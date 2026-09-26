"""
Adattatore di protocollo BSPL locale basato sul modello LoST (Local State Transfer).

Incapsula la gestione dello stato relazionale locale di ciascun nodo partecipante:
- Mantenimento delle relazioni locali R(m) per ciascuno schema di messaggio m.
- Regole formali di viabilità per l'emissione dei messaggi:
  * verifica e recupero dei parametri [in] dallo stato locale;
  * verifica che nessun parametro [out] sia già vincolato per la chiave ID (immutabilità);
  * verifica che nessun parametro [nil] sia già vincolato per la chiave ID.
- Controlli di consistenza semantica (immutabilità BSPL) in ricezione.
- Controlli di idempotenza (duplicati identici).
- Estrazione della storia locale del ruolo per l'History Vector distribuito H_x.
"""

import logging
from typing import Any, Dict, List, Optional

from roles.exceptions import BSPLViabilityError, BSPLConsistencyError

logger = logging.getLogger("BSPLAdapter")


class BSPLAdapter:
    """
    Adattatore LoST locale integrato nel nodo di ruolo.
    Mantiene e valida lo stato informativo del partecipante in modo autonomo.
    """

    def __init__(self, role_name: str = ""):
        self.role_name = role_name
        # Relazioni locali LoST: schema_name -> { transaction_ID: { param_name: param_value } }
        self.relations: Dict[str, Dict[str, Dict[str, Any]]] = {}

    def has_known_parameter(self, param: str, ID: str) -> bool:
        """
        Verifica se il parametro indicato è già vincolato in una qualsiasi delle
        relazioni locali del ruolo per la transazione identificata da ID.
        """
        for table in self.relations.values():
            if ID in table and param in table[ID]:
                return True
        return False

    def get_known_parameter(self, param: str, ID: str) -> Any:
        """
        Restituisce il valore del parametro se già vincolato in una qualsiasi delle
        relazioni locali del ruolo per l'ID indicato, altrimenti None.
        """
        for table in self.relations.values():
            if ID in table and param in table[ID]:
                return table[ID][param]
        return None

    def check_viability(
        self,
        ID: str,
        in_params: Optional[List[str]] = None,
        out_params: Optional[List[str]] = None,
        nil_params: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Verifica le condizioni formali di viabilità LoST/BSPL per l'emissione di un messaggio:
        1. Tutti i parametri in_params (se presenti nello schema) devono risultare già vincolati
           nelle relazioni locali per ID.
        2. Nessun parametro out_params (se presente nello schema) deve risultare già vincolato
           per la chiave ID (assioma di immutabilità).
        3. Nessun parametro nil_params (se presente nello schema) deve risultare già vincolato
           per la chiave ID.

        Ritorna il dizionario dei parametri [in] risolti dallo stato locale: { param_name: param_value }.
        """
        resolved_in_params: Dict[str, Any] = {}

        # 1. Verifica e recupero parametri [in] dallo stato locale
        for param in in_params or []:
            if not self.has_known_parameter(param, ID):
                prefix = f"[{self.role_name}] " if self.role_name else ""
                raise BSPLViabilityError(
                    f"{prefix}Emissione non viabile: parametro [in] '{param}' non ancora noto per ID='{ID}'"
                )
            resolved_in_params[param] = self.get_known_parameter(param, ID)

        # 2. Verifica che nessun parametro [out] sia già vincolato
        for param in out_params or []:
            if self.has_known_parameter(param, ID):
                known = self.get_known_parameter(param, ID)
                prefix = f"[{self.role_name}] " if self.role_name else ""
                raise BSPLViabilityError(
                    f"{prefix}Emissione non viabile: parametro [out] '{param}' già vincolato "
                    f"(valore={known!r}) per ID='{ID}'"
                )

        # 3. Verifica che nessun parametro [nil] sia già vincolato
        for param in nil_params or []:
            if self.has_known_parameter(param, ID):
                known = self.get_known_parameter(param, ID)
                prefix = f"[{self.role_name}] " if self.role_name else ""
                raise BSPLViabilityError(
                    f"{prefix}Emissione non viabile: parametro [nil] '{param}' già vincolato "
                    f"(valore={known!r}) per ID='{ID}'"
                )

        return resolved_in_params

    def check_consistency(self, ID: str, params: Dict[str, Any]):
        """
        Verifica la consistenza semantica in ricezione (assioma di immutabilità BSPL):
        Per ciascun parametro ricevuto, se è già noto nello stato locale del ruolo per quell'ID,
        il valore in arrivo DEVE coincidere esattamente con quello registrato.
        """
        for param, val in params.items():
            if self.has_known_parameter(param, ID):
                known = self.get_known_parameter(param, ID)
                if known != val:
                    prefix = f"[{self.role_name}] " if self.role_name else ""
                    raise BSPLConsistencyError(
                        f"{prefix}Violazione consistenza BSPL: parametro '{param}' ricevuto con valore {val!r} "
                        f"incompatibile con il valore già registrato {known!r} per ID='{ID}'"
                    )

    def is_duplicate(self, schema: str, ID: str, params: Dict[str, Any]) -> bool:
        """
        Verifica se la tupla del messaggio è un duplicato idempotente già registrato in R(schema).
        """
        table = self.relations.get(schema, {})
        return ID in table and table[ID] == params

    def insert_relation(self, schema: str, ID: str, params: Dict[str, Any]):
        """
        Inserisce la tupla convalidata all'interno della relazione locale R(schema).
        """
        if schema not in self.relations:
            self.relations[schema] = {}
        self.relations[schema][ID] = dict(params)

    def remove_relation(self, schema: str, ID: str):
        """
        Rimuove una tupla da R(schema) in caso di errore durante la trasmissione (rollback locale).
        """
        if schema in self.relations and ID in self.relations[schema]:
            del self.relations[schema][ID]

    def get_history(self, ID: str) -> Dict[str, Dict[str, Any]]:
        """
        Restituisce la storia locale H_x (le tuple delle relazioni locali popolate)
        per una data transazione ID, corrispondente alla componente del ruolo
        all'interno dell'History Vector H = [H_x1, ..., H_xn] (Cap. 1, Sez. 1.3.2).
        """
        return {
            schema: dict(table[ID])
            for schema, table in self.relations.items()
            if ID in table
        }
