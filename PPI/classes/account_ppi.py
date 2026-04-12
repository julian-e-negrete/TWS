# Imports 
from ppi_client.api.constants import ACCOUNTDATA_TYPE_ACCOUNT_NOTIFICATION, ACCOUNTDATA_TYPE_PUSH_NOTIFICATION, \
    ACCOUNTDATA_TYPE_ORDER_NOTIFICATION
from ppi_client.models.account_movements import AccountMovements
from ppi_client.models.bank_account_request import BankAccountRequest
from ppi_client.models.foreign_bank_account_request import ForeignBankAccountRequest, ForeignBankAccountRequestDTO
from ppi_client.models.cancel_bank_account_request import CancelBankAccountRequest
from ppi_client.models.order import Order
from ppi_client.ppi import PPI
from ppi_client.models.order_budget import OrderBudget
from ppi_client.models.order_confirm import OrderConfirm
from ppi_client.models.disclaimer import Disclaimer

from datetime import datetime, timedelta
import os


class Account:
    
    
    def __init__(self, P_ppi ) -> None:
        self.ppi = P_ppi
        self.login_to_api()
        self.account_number = self.get_account_information()
        
    
    def login_to_api(self):
        """Logs into the API using credentials from settings."""
        from finance.config import settings
        public_key = settings.ppi.public_key
        private_key = settings.ppi.private_key
        self.ppi.account.login_api(public_key, private_key)


    def get_account_information(self):
        """Fetches and prints account information."""
        print("Getting accounts information")
        account_numbers = self.ppi.account.get_accounts()
        
        print(f"\n Numero de cuenta: {account_numbers[0]['accountNumber']}  nombre: {account_numbers[0]['name']}")
        
        return account_numbers[0]['accountNumber']
    
    def get_available_balance(self):
        """Fetches and prints available balance for the specified account."""
        print(f"\nGetting available balance of {self.account_number}")
        balances = self.ppi.account.get_available_balance(self.account_number)
        for balance in balances:
            print("Currency %s - Settlement %s - Amount %s %s" % (
                balance['name'], balance['settlement'], balance['symbol'], balance['amount']))

        
    def get_movements_by_date(self):
    # Getting movements
        print("\nGetting movements of %s" % self.account_number)
        movements = self.ppi.account.get_movements(AccountMovements(self.account_number, datetime(2021, 12,1),
                                                               datetime(2024, 12, 31), None))
        for mov in movements:
            
            datetime_str =  mov['settlementDate']
            print(datetime_str)

            #datetime_object = datetime.strptime(datetime_str, "%Y-%m-%d")
            
            print("%s %s - Currency %s Amount %s " % (
                datetime_str, mov['description'], mov['currency'], mov['amount']))


    #region orders get
    def get_orders(self):
        # Get orders
        print("\nGet orders")
        orders = self.ppi.orders.get_orders(self.account_number, date_from=datetime.today() + timedelta(days=-100),
                                       date_to=datetime.today())
        for order in orders:
            print(order)
    
    def get_active_orders(self):
        # Get active orders
        print("\nGet active orders")
        active_orders = self.ppi.orders.get_active_orders(self.account_number)
        for order in active_orders:
            print(order)
    
    def get_order_detail(self, order_id ):
        
        # Get order detail
        print("\nGet order detail")
        detail = self.ppi.orders.get_order_detail(self.account_number, order_id, None)
        print(detail)
    
    #endregion
    
    
    #region orders post
    
    #region create_order
    def create_order(self):
        # Get budget
        print("\nGet budget for the order")
        budget_order = self.ppi.orders.budget(OrderBudget(self.account_number, 10000, 150, "GGAL", "ACCIONES", "Dinero",
                                                     "PRECIO-LIMITE", "HASTA-SU-EJECUCIÓN", None, "Compra",
                                                     "INMEDIATA"))
        print(budget_order)
        disclaimers_order = budget_order['disclaimers'] 
    
    
    
    def confirm_order(self, disclaimers_order):
        
        # Confirm order
        print("\nConfirm order")
        accepted_disclaimers = []
        for disclaimer in disclaimers_order:
            accepted_disclaimers.append(Disclaimer(disclaimer['code'], True))
        confirmation =self. ppi.orders.confirm(OrderConfirm(self.account_number, 10000, 150, "GGAL", "ACCIONES", "Dinero",
                                                       "PRECIO-LIMITE", "HASTA-SU-EJECUCIÓN", None, "Compra"
                                                       , "INMEDIATA", accepted_disclaimers, None))
        print(confirmation)
        order_id = confirmation["id"]
        
    #endregion
    
    #region stop_order
    def create_stop_order(self):
        
        # Get budget
        print("\nGet budget for the stop order")
        budget_stop_order = self.ppi.orders.budget(OrderBudget(self.account_number, 1000, 3000.5, "GOOGL", "CEDEARS",
                                                          "Papeles", "PRECIO-LIMITE", "HASTA-SU-EJECUCIÓN", None,
                                                          "Stop Order", "INMEDIATA", 2998.5))
        print(budget_stop_order)
        disclaimers_stop_order = budget_stop_order['disclaimers'] 




    def confirm_stop_order(self,disclaimers_stop_order):
        # Confirm stop order
        print("\nConfirm stop order")
        accepted_disclaimers = []
        for disclaimer in disclaimers_stop_order:
            accepted_disclaimers.append(Disclaimer(disclaimer['code'], True))
        stop_order_confirmation = self.ppi.orders.confirm(OrderConfirm(self.account_number, 1000, 3000.5, "GOOGL", "CEDEARS",
                                                                  "Papeles", "PRECIO-LIMITE", "HASTA-SU-EJECUCIÓN",
                                                                  None, "Stop Order", "INMEDIATA",
                                                                  accepted_disclaimers, None, 2998.5))
        print(stop_order_confirmation)
        stop_order_id = stop_order_confirmation["id"]
        
    #endregion
    
    #region cancelation_order
    def cancelation_order(self,order_id):
        # Cancel order
        print("\nCancel order")
        cancel = self.ppi.orders.cancel_order(Order(order_id, self.account_number, None))
        print(cancel)
        
    def mass_cancelation(self):
        # Cancel all active orders
        print("\nMass Cancel")
        cancels = self.ppi.orders.mass_cancel_order(self.account_number)
        print(cancels)
        
    #endregion
    
    #endregion
    
    
    
    #region bank
    def register_bank_account(self):
    # Register a bank account
        print("\nRegistering bank account")
        bank_account_request = self.ppi.account.register_bank_account(
            BankAccountRequest(self.account_number, currency="ARS", cbu="", cuit="00000000000",
                               alias="ALIASCBU", bank_account_number=""))
        print(bank_account_request)
        
        
    def register_foreign_bank_account(self):
    # Register a foreign bank account
        print("\nRegistering foreign bank account")
        data = ForeignBankAccountRequestDTO(account_number=self.account_number, cuit="00000000000", intermediary_bank="",
                                            intermediary_bank_account_number="", intermediary_bank_swift="",
                                            bank="The Bank of Tokyo-Mitsubishi, Ltd.", bank_account_number="12345678",
                                            swift="ABC", ffc="Juan Perez")
        extract_file_route = r"C:\Documents\example.pdf"
        extract_file = (os.path.basename(extract_file_route), open(extract_file_route, 'rb'))
        foreign_bank_account_request = self.ppi.account.register_foreign_bank_account(
            ForeignBankAccountRequest(data, extract_file))
        print(foreign_bank_account_request)
        
    def cancel_bank_account(self):
        # Cancel a bank account
        print("\nCanceling bank account")
        cancel_bank_account_request = self.ppi.account.cancel_bank_account(
            CancelBankAccountRequest(self.account_number, cbu="0000000000000000000000", bank_account_number=""))
        print(cancel_bank_account_request)
        
    #endregion
    
    
    