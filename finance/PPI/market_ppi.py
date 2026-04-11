# Imports 
from ppi_client.ppi import PPI

from ppi_client.models.instrument import Instrument
from datetime import datetime, timedelta
from ppi_client.models.estimate_bonds import EstimateBonds

from tabulate import tabulate 


import json
import traceback
import math
import os



class Market_data:
    
    def __init__(self, P_ppi ) -> None:
        self.ppi = P_ppi
        self.instruments = []
        
        
    #region master
    
    
    #region types of
    def get_instruments_type(self):
        # Getting instrument types
        print("\nGetting instrument types")
        instruments = self.ppi.configuration.get_instrument_types()
            
        return instruments
            
    def select_instrument_type(self):
        instruments = self.get_instruments_type()
        for i in range(len(instruments)):
            print(f"{i}) -- {instruments[i]}")    
        
        while True:
                
            option :int = input("Ingrese el numero de instrumento: ")
            try:
                option = int(option)
            except Exception as e:
                return e
            if option < 0 or option > len(instruments) -1:
                print("Seleccione una opcion correcta.")
            else:
                break
            
        return instruments[option]
    
    
    def get_markets(self):
        # Getting markets
        print("\nGetting markets")
        markets = self.ppi.configuration.get_markets()
        for item in markets:
            print(item)
            
            
    def get_settlements(self):
        # Getting settlements
        print("\nGetting settlements")
        settlements = self.ppi.configuration.get_settlements()
        for item in settlements:
            print(item)
            
            
    def get_quantity_types(self):
        # Getting quantity types
        print("\nGetting quantity types")
        quantity_types = self.ppi.configuration.get_quantity_types()
        for item in quantity_types:
            print(item)
            

    def get_operation_terms(self):
        # Getting operation terms
        print("\nGetting operation terms")
        operation_terms = self.ppi.configuration.get_operation_terms()
        for item in operation_terms:
            print(item)
            
            
    def get_operations(self):
        # Getting operations
        print("\nGetting operations")
        operations = self.ppi.configuration.get_operations()
        for item in operations:
            print(item)
            
    #endregion
    
    
    
    #region holidays        
    def get_holidays(self):
        # Get holidays
        print("\nGet local holidays for the current year")
        holidays = self.ppi.configuration.get_holidays(start_date=datetime(2022, 1, 1), end_date=datetime(2022, 12, 31))
        for holiday in holidays:
            print("%s - %s " % (holiday["date"][0:10], holiday["description"]))
        
        print("\nGet USA holidays for the current year")
        holidays = self.ppi.configuration.get_holidays(start_date=datetime(2022, 1, 1), end_date=datetime(2022, 12, 31),
                                                  is_usa=True)
        for holiday in holidays:
            print("%s - %s " % (holiday["date"][0:10], holiday["description"]))
    
    
    
    def isHoliday (self) -> bool:
        # Check holidays
        print("\nIs today a local holiday?")
        print(self.ppi.configuration.is_local_holiday())
        print("\nIs today a holiday in the USA?")
        print(self.ppi.configuration.is_usa_holiday())
    
    #endregion   
    
    
    #endregion     
            
            
            
    #region search
    
    
    #search instrument, get all that is related to that instrument
    def get_instrument(self, ticker: str,market: str, type_instrument: str ):
        # Search Instrument
        #print("\nSearching instruments")
        instruments = self.ppi.marketdata.search_instrument(ticker.upper(), "", market, type_instrument)
        
        table_data = [
            [ins["ticker"], ins["description"], ins["currency"], ins["type"]]
            for ins in instruments
        ]
        
                # Define headers
        headers = ["ticker", "description", "currency", "type"]

        # Set the width for the box
        box_width = 12

        # Generate the formatted box
        """
        print("-" * (box_width+ 2))
        print(f"| {ticker.center(box_width - 2)} |")
        print("-" * (box_width + 2))
        # Print the table
        print(tabulate(table_data, headers=headers, tablefmt="grid"))
        """
        """
        for ins in instruments:
            print(f"Ticker: {ins["ticker"]}\t Descripcion: {ins["description"]}\t Moneda: {ins["currency"]}\t Tipo: {ins["type"]}")
        """ 
        return instruments
            
    def search_current_book(self, ticker: str, type_: str, time: str):
        # Search Current Book
        print("\nSearching Current Book")
        current_book = self.ppi.marketdata.book(ticker.upper(), type_, time)
        print(current_book)
        
        
    
    # search historic market data
    def get_historical_data(self, ticker: str, type_: str, time: str, start_date, end_date):
        
        #print("\nSearching MarketData")
        if ticker == "":
            ticker = input("ingrese el ticker que quiere buscar: ")
            type_ = self.select_instrument_type()
            os.system("cls")
        try:
            start_date = datetime.strptime(start_date, "%Y-%m-%d")
            end_date = datetime.strptime(end_date, "%Y-%m-%d")
            
        except Exception as error:
                while True:
                    date_input = input("Enter start date (YYYY-MM-DD): ")
                    date_input2 = input("Enter end date (YYYY-MM-DD): ")
                    try:
                        # Try to parse the input into a datetime object
                        start_date = datetime.strptime(date_input, "%Y-%m-%d")
                        end_date = datetime.strptime(date_input2, "%Y-%m-%d")
                        
                        break  # Exit the loop if the date is valid
                    except ValueError:
                        print("Invalid date format. Please use YYYY-MM-DD.")


        market_data = self.ppi.marketdata.search(ticker.upper(), type_, time, start_date, end_date)
        """
        table_data = [
            [ins["date"], ins["price"], ins["volume"], ins["openingPrice"], ins["min"], ins["max"]]
            for ins in market_data
        ]
        
                # Define headers
        headers = ["Date", "Price", "Volume", "Opening Price", "Min", "Max"]

        # Set the width for the box
        box_width = 12

        # Generate the formatted box
        print("-" * (box_width+ 2))
        print(f"| {ticker.center(box_width - 2)} |")
        print("-" * (box_width + 2))
        # Print the table
        print(tabulate(table_data, headers=headers, tablefmt="grid"))
        """
        return market_data
            
            
    
    # Search intraday data
    def get_intraday_market_data(self, ticker, type_instrument, time):
        # Search Intraday MarketData
        print("\nSearching Intraday MarketData")
        intraday_market_data = self.ppi.marketdata.intraday(ticker.upper(), type_instrument, time)
        
        
        box_width = 12

         # Generate the formatted box
        print("-" * (box_width + 2))
        print(f"| {ticker.center(box_width - 2)} |")
        print("-" * (box_width + 2))
        
            
        table_data = [
            [ins["date"], ins["price"], ins["volume"]]
            for ins in intraday_market_data
        ]
        
                # Define headers
        headers = ["Date", "Price", "Volume", "Opening Price", "Min", "Max"]
        
        print(tabulate(table_data, headers=headers, tablefmt="grid"))

        
       
    
    # Search Current MarketData        
    def get_market_data(self, ticker, type_instrument, time):
        if(ticker == ""):
            ticker = input("ingrese el ticker que quiere buscar: ")
        current_market_data = self.ppi.marketdata.current(ticker.upper(), type_instrument, time)
        """
        print("\nSearching Current MarketData")
        print(ticker.upper())
        print("-----------------------------------------")
        
        #date_object = datetime.strptime(current_market_data["date"],  "%Y-%m-%dT%H:%M:%S%z")

        #formatted_date = date_object.strftime("%d-%m-%Y")  # Example: "23-Dec-2024"

        #print(current_market_data)
        print(f"fecha :{current_market_data["date"],}\t Precio: {current_market_data["price"]}\t Volumen: {current_market_data["volume"]}")
        """
        return current_market_data
               
    #endregion
    
    
    def estimate_bond(self, ticker, cantidad, precio):
        print("\nEstimate bond\n")

        if ticker == "":
            ticker = input("Ingrese el ticker: ").upper()
            cantidad = int(input("Ingrese la cantidad: "))
            precio = float(input("Ingrese el precio: "))
            
        estimate = self.ppi.marketdata.estimate_bonds(
            EstimateBonds(ticker=ticker, date=datetime.today(), quantityType="PAPELES", quantity=cantidad, price=precio)
        )

        print("FLOWS")
        total = 0
        for i in range(len(estimate["flows"])):
            date_object = datetime.strptime(estimate["flows"][i]["cuttingDate"], "%Y-%m-%dT%H:%M:%S%z")
            formatted_date = date_object.strftime("%d-%m-%Y")
            
            print(f"Fecha: {formatted_date}", end="  ")
            print(f"Residual Value: %{estimate['flows'][i]['residualValue'] * 100:.2f}", end="  ")
            print(f"Interes: ${estimate['flows'][i]['rent']:.2f}", end="  ")
            print(f"Amortizacion: ${estimate['flows'][i]['amortization']:.2f}", end="  ")
            print(f"Total: ${estimate['flows'][i]['total']:.2f}")
            
            total += estimate["flows"][i]["total"]

        print(f"Total obtenido en el vencimiento: {total:.2f}")

        print("\n\nSENSITIVITY")
        for i in range(len(estimate["sensitivity"])):
            print(f"TIR: {estimate['sensitivity'][i]['tir']:.2f}", end=" \t ")
            print(f"Precio: ${estimate['sensitivity'][i]['price']:.2f}", end=" \t ")
            print(f"Paridad: {estimate['sensitivity'][i]['parity']:.2f}", end=" \t ")
            print(f"Variacion: %{estimate['sensitivity'][i]['variation'] * 100:.2f}")

        print(estimate["tir"])

                  
    #region realtime
    
    def add_instrument(self, ticker: str, type_ :str, settlement: str):
        """
        Adds an instrument to the subscription list.

        Args:
            ticker (str): The instrument's ticker symbol.
            type_ (str): The type of the instrument (e.g., ACCIONES, BONOS).
            settlement (str): The settlement type (e.g., A-48HS, INMEDIATA).
        """
        self.instruments.append((ticker, type_, settlement))
        

    def on_connect(self):
        """Handles the connection to the real-time market data."""
        try:
            print("\nConnected to real-time market data")
            for ticker, type_, settlement in self.instruments:
                self.ppi.realtime.subscribe_to_element(Instrument(ticker, type_, settlement))
        except Exception as error:
            print("Error during connection:")
            traceback.print_exc()

    def on_disconnect(self):
        try:
            print("\nDisconnected from real-time market data")
        except Exception as error:
            print("Error during disconnection:")
            traceback.print_exc()

    def on_market_data(self, data):
        try:
            msg = json.loads(data)
            if(msg['Price'] == 78000):
                print("LLEGO A 78000")
                return
            if msg.get("Trade"):
                print("%s [%s-%s] Price %.2f Volume %.2f" % (
                    msg['Date'], msg['Ticker'], msg['Settlement'], msg['Price'], msg['VolumeAmount']))
            else:
                bid = msg['Bids'][0]['Price'] if msg.get('Bids') else 0
                offer = msg['Offers'][0]['Price'] if msg.get('Offers') else 0
                print(
                    "%s [%s-%s] Offers: %.2f-%.2f Opening: %.2f MaxDay: %.2f MinDay: %.2f Accumulated Volume %.2f" %
                    (
                        msg['Date'], msg['Ticker'], msg['Settlement'], bid, offer,
                        msg['OpeningPrice'], msg['MaxDay'], msg['MinDay'], msg['VolumeTotalAmount']))
        except Exception as error:
            print(datetime.now())
            traceback.print_exc()

    def start(self):
        """Starts the real-time connections."""
        try:
            self.ppi.realtime.connect_to_market_data(
                self.on_connect,
                self.on_disconnect,
                self.on_market_data
            )
            self.ppi.realtime.start_connections()
        except Exception as error:
            print(datetime.now())
            print("Error during start:")
            traceback.print_exc()
                
    #endregion
    
    
    
    
    
    